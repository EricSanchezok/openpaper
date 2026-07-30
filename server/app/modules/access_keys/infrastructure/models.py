"""SQLAlchemy persistence model for Scholens AccessKeys."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.shared.infrastructure.persistence import Base
from sqlalchemy import (
    BigInteger,
    CHAR,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class AccessKey(Base):
    __tablename__ = "access_keys"
    __table_args__ = (
        CheckConstraint(
            "length(name) BETWEEN 1 AND 80 AND name = btrim(name)",
            name="ck_access_keys_name",
        ),
        CheckConstraint(
            "secret_hash ~ '^[0-9a-f]{64}$'",
            name="ck_access_keys_secret_hash",
        ),
        CheckConstraint(
            "length(key_prefix) = 20",
            name="ck_access_keys_key_prefix",
        ),
        CheckConstraint(
            "permissions IN ("
            "ARRAY['read']::text[], "
            "ARRAY['write']::text[], "
            "ARRAY['delete']::text[], "
            "ARRAY['read','write']::text[], "
            "ARRAY['read','delete']::text[], "
            "ARRAY['write','delete']::text[], "
            "ARRAY['read','write','delete']::text[]"
            ")",
            name="ck_access_keys_permissions",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_access_keys_expiration",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_access_keys_revoked_at",
        ),
        CheckConstraint(
            "last_used_at IS NULL OR last_used_at >= created_at",
            name="ck_access_keys_last_used_at",
        ),
        {"schema": "scholens"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    secret_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


Index(
    "uq_access_keys_secret_hash",
    AccessKey.secret_hash,
    unique=True,
)
Index(
    "ix_access_keys_user_created",
    AccessKey.user_id,
    AccessKey.created_at.desc(),
    AccessKey.id.desc(),
)
Index(
    "ix_access_keys_user_revoked",
    AccessKey.user_id,
    AccessKey.revoked_at,
)
