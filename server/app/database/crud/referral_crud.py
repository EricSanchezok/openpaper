import logging
import secrets
import string
import uuid
from datetime import datetime
from typing import TypedDict

from app.database.crud.base_crud import CRUDBase
from app.database.models import (
    Referral,
    ReferralAttributionMethod,
    ReferralCode,
    ReferralStatus,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ReferralSummary(TypedDict):
    total_referrals: int
    total_converted: int
    pending_cents: int
    available_cents: int


CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 7
CODE_MAX_GENERATION_ATTEMPTS = 8


class ReferralCodeCreate(BaseModel):
    user_id: int
    code: str


class ReferralCodeUpdate(BaseModel):
    code: str | None = None


class ReferralCreate(BaseModel):
    referrer_user_id: int
    referee_user_id: int
    code_used: str
    attribution_method: str = ReferralAttributionMethod.LINK.value
    status: str = ReferralStatus.ATTRIBUTED.value
    referrer_credit_cents: int = 600


class ReferralUpdate(BaseModel):
    status: str | None = None
    converted_at: datetime | None = None
    credit_available_at: datetime | None = None
    referee_coupon_id: str | None = None
    stripe_balance_transaction_id: str | None = None
    fraud_reason: str | None = None


def _generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


class CRUDReferralCode(CRUDBase[ReferralCode, ReferralCodeCreate, ReferralCodeUpdate]):
    def get_by_user_id(self, db: Session, user_id: int) -> ReferralCode | None:
        return db.scalars(
            select(ReferralCode).where(ReferralCode.user_id == user_id)
        ).first()

    def get_by_code(self, db: Session, code: str) -> ReferralCode | None:
        return db.scalars(
            select(ReferralCode).where(ReferralCode.code == code.upper())
        ).first()

    def get_or_create_for_user(
        self, db: Session, user_id: int
    ) -> tuple[ReferralCode, bool]:
        """Returns (code, newly_created). The bool lets callers fire a
        telemetry event when a code is generated for the first time."""
        existing = self.get_by_user_id(db, user_id)
        if existing:
            return existing, False

        for _ in range(CODE_MAX_GENERATION_ATTEMPTS):
            candidate = _generate_code()
            if self.get_by_code(db, candidate) is None:
                obj = ReferralCode(user_id=user_id, code=candidate)
                db.add(obj)
                db.commit()
                db.refresh(obj)
                return obj, True

        raise RuntimeError("Could not generate a unique referral code")


class CRUDReferral(CRUDBase[Referral, ReferralCreate, ReferralUpdate]):
    def get_by_id(self, db: Session, referral_id: uuid.UUID) -> Referral | None:
        """Fetch a referral by its primary key.

        Referrals are not user-scoped — callers (e.g. the internal settlement
        webhook) authenticate via the unguessable referral UUID itself.
        """
        return db.get(Referral, referral_id)

    def get_by_referee(self, db: Session, referee_user_id: int) -> Referral | None:
        return db.scalars(
            select(Referral).where(Referral.referee_user_id == referee_user_id)
        ).first()

    def get_attributed_for_referee(
        self, db: Session, referee_user_id: int
    ) -> Referral | None:
        return db.scalars(
            select(Referral).where(
                Referral.referee_user_id == referee_user_id,
                Referral.status == ReferralStatus.ATTRIBUTED.value,
            )
        ).first()

    def create_attribution(
        self,
        db: Session,
        *,
        referrer_user_id: int,
        referee_user_id: int,
        code_used: str,
        attribution_method: ReferralAttributionMethod,
    ) -> Referral | None:
        obj = Referral(
            referrer_user_id=referrer_user_id,
            referee_user_id=referee_user_id,
            code_used=code_used,
            attribution_method=attribution_method.value,
            status=ReferralStatus.ATTRIBUTED.value,
        )
        try:
            db.add(obj)
            db.commit()
            db.refresh(obj)
            return obj
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating referral attribution: {e}", exc_info=True)
            return None

    def set_referee_coupon(
        self, db: Session, referral: Referral, coupon_id: str
    ) -> Referral:
        setattr(referral, "referee_coupon_id", coupon_id)
        db.commit()
        db.refresh(referral)
        return referral

    def mark_credit_pending(
        self,
        db: Session,
        referral: Referral,
        *,
        converted_at: datetime,
        credit_available_at: datetime,
    ) -> Referral:
        setattr(referral, "status", ReferralStatus.CREDIT_PENDING.value)
        setattr(referral, "converted_at", converted_at)
        setattr(referral, "credit_available_at", credit_available_at)
        db.commit()
        db.refresh(referral)
        return referral

    def mark_credit_available(
        self,
        db: Session,
        referral: Referral,
        *,
        stripe_balance_transaction_id: str,
    ) -> Referral:
        setattr(referral, "status", ReferralStatus.CREDIT_AVAILABLE.value)
        setattr(
            referral,
            "stripe_balance_transaction_id",
            stripe_balance_transaction_id,
        )
        db.commit()
        db.refresh(referral)
        return referral

    def mark_rejected_fraud(
        self, db: Session, referral: Referral, reason: str
    ) -> Referral:
        setattr(referral, "status", ReferralStatus.REJECTED_FRAUD.value)
        setattr(referral, "fraud_reason", reason)
        db.commit()
        db.refresh(referral)
        return referral

    def mark_clawed_back(
        self, db: Session, referral: Referral, reason: str
    ) -> Referral:
        setattr(referral, "status", ReferralStatus.CLAWED_BACK.value)
        setattr(referral, "fraud_reason", reason)
        db.commit()
        db.refresh(referral)
        return referral

    def get_summary_for_referrer(
        self, db: Session, referrer_user_id: int
    ) -> ReferralSummary:
        rows = (
            db.execute(
                select(
                    Referral.status,
                    func.count(Referral.id),
                    func.coalesce(func.sum(Referral.referrer_credit_cents), 0),
                )
                .where(Referral.referrer_user_id == referrer_user_id)
                .group_by(Referral.status)
            )
            .tuples()
            .all()
        )

        counts: dict[str, int] = {s.value: 0 for s in ReferralStatus}
        cents: dict[str, int] = {s.value: 0 for s in ReferralStatus}
        for status, count, total in rows:
            counts[status] = int(count)
            cents[status] = int(total)

        pending_cents = cents[ReferralStatus.CREDIT_PENDING.value]
        available_cents = cents[ReferralStatus.CREDIT_AVAILABLE.value]
        total_converted = (
            counts[ReferralStatus.CREDIT_PENDING.value]
            + counts[ReferralStatus.CREDIT_AVAILABLE.value]
        )

        return {
            "total_referrals": sum(counts.values()),
            "total_converted": total_converted,
            "pending_cents": pending_cents,
            "available_cents": available_cents,
        }


referral_code_crud = CRUDReferralCode(ReferralCode)
referral_crud = CRUDReferral(Referral)
