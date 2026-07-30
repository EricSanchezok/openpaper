"""PostgreSQL AccessKey persistence adapter."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from app.modules.access_keys.application.ports import (
    AccessKeyListPosition,
    AccessKeyRecord,
)
from app.modules.access_keys.infrastructure.models import AccessKey
from app.shared.domain import WorkspacePermission
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.orm import Session

_CAPACITY_LOCK_NAMESPACE = "scholens.access_keys.capacity.v1"


class SqlAlchemyAccessKeyGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def acquire_creation_lock(self, *, user_id: int) -> None:
        self._db.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtextextended(:namespace, :user_id))"
            ),
            {
                "namespace": _CAPACITY_LOCK_NAMESPACE,
                "user_id": user_id,
            },
        )

    def count_active(self, *, user_id: int, now: datetime) -> int:
        return int(
            self._db.scalar(
                select(func.count())
                .select_from(AccessKey)
                .where(
                    AccessKey.user_id == user_id,
                    AccessKey.revoked_at.is_(None),
                    or_(
                        AccessKey.expires_at.is_(None),
                        AccessKey.expires_at > now,
                    ),
                )
            )
            or 0
        )

    def create(
        self,
        *,
        user_id: int,
        name: str,
        secret_hash: str,
        key_prefix: str,
        permissions: tuple[WorkspacePermission, ...],
        expires_at: datetime | None,
        now: datetime,
    ) -> AccessKeyRecord:
        model = AccessKey(
            id=uuid4(),
            user_id=user_id,
            name=name,
            secret_hash=secret_hash,
            key_prefix=key_prefix,
            permissions=[permission.value for permission in permissions],
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        self._db.add(model)
        self._db.flush()
        return _record(model)

    def list_owned(
        self,
        *,
        user_id: int,
        limit: int,
        before: AccessKeyListPosition | None,
    ) -> list[AccessKeyRecord]:
        statement = select(AccessKey).where(AccessKey.user_id == user_id)
        if before is not None:
            statement = statement.where(
                or_(
                    AccessKey.created_at < before.created_at,
                    and_(
                        AccessKey.created_at == before.created_at,
                        AccessKey.id < before.id,
                    ),
                )
            )
        models = self._db.scalars(
            statement.order_by(
                AccessKey.created_at.desc(),
                AccessKey.id.desc(),
            ).limit(limit)
        ).all()
        return [_record(model) for model in models]

    def lock_owned(
        self,
        *,
        user_id: int,
        access_key_id: UUID,
    ) -> AccessKeyRecord | None:
        model = self._db.scalar(
            select(AccessKey)
            .where(
                AccessKey.id == access_key_id,
                AccessKey.user_id == user_id,
            )
            .with_for_update()
        )
        return _record(model) if model is not None else None

    def lock_by_secret_hash(
        self,
        *,
        secret_hash: str,
    ) -> AccessKeyRecord | None:
        model = self._db.scalar(
            select(AccessKey)
            .where(AccessKey.secret_hash == secret_hash)
            .with_for_update()
        )
        return _record(model) if model is not None else None

    def update(
        self,
        *,
        access_key_id: UUID,
        name: str,
        permissions: tuple[WorkspacePermission, ...],
        now: datetime,
    ) -> AccessKeyRecord:
        model = self._db.get(AccessKey, access_key_id)
        if model is None:
            raise RuntimeError("locked access key disappeared before update")
        model.name = name
        model.permissions = [permission.value for permission in permissions]
        model.updated_at = now
        self._db.flush()
        return _record(model)

    def revoke(
        self,
        *,
        access_key_id: UUID,
        now: datetime,
    ) -> None:
        model = self._db.get(AccessKey, access_key_id)
        if model is None:
            raise RuntimeError("locked access key disappeared before revocation")
        model.revoked_at = now
        model.updated_at = now
        self._db.flush()

    def touch_last_used(
        self,
        *,
        access_key_id: UUID,
        now: datetime,
        stale_before: datetime,
    ) -> None:
        self._db.execute(
            update(AccessKey)
            .where(
                AccessKey.id == access_key_id,
                or_(
                    AccessKey.last_used_at.is_(None),
                    AccessKey.last_used_at <= stale_before,
                ),
            )
            .values(last_used_at=now, updated_at=now)
        )


def _record(model: AccessKey) -> AccessKeyRecord:
    return AccessKeyRecord(
        id=model.id,
        user_id=model.user_id,
        name=model.name,
        key_prefix=model.key_prefix,
        permissions=tuple(WorkspacePermission(value) for value in model.permissions),
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        last_used_at=model.last_used_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
