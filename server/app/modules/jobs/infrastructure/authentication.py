"""Transactional replay ledger for Jobs callback nonces."""

from datetime import UTC, datetime, timedelta

from app.database.database import SessionLocal
from app.database.models import JobsWebhookNonce
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError


class SqlAlchemyCallbackNonceStore:
    def reserve(self, nonce: str) -> bool:
        try:
            with SessionLocal.begin() as db:
                db.execute(
                    delete(JobsWebhookNonce).where(
                        JobsWebhookNonce.created_at
                        < datetime.now(UTC) - timedelta(minutes=10)
                    )
                )
                db.add(JobsWebhookNonce(nonce=nonce))
        except IntegrityError:
            return False
        return True
