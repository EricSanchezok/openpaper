"""SQLAlchemy model for append-only operation attribution."""

from __future__ import annotations

from uuid import UUID

from app.shared.infrastructure.persistence import Base
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class OperationJournalEntryModel(Base):
    __tablename__ = "operation_journal_entries"
    __table_args__ = (
        CheckConstraint(
            "initiated_by IN ('user', 'agent', 'system')",
            name="ck_operation_journal_initiator",
        ),
        CheckConstraint(
            "origin_kind IN ("
            "'http', 'conversation', 'mcp', 'job', 'webhook', "
            "'oauth_callback', 'scheduler'"
            ")",
            name="ck_operation_journal_origin",
        ),
        CheckConstraint(
            "credential_kind IS NULL OR credential_kind IN ("
            "'cloud_session', 'access_key', 'internal_signature', "
            "'provider_signature'"
            ")",
            name="ck_operation_journal_credential",
        ),
        CheckConstraint(
            "action ~ '^[a-z][a-z0-9_]{0,62}\\.[a-z][a-z0-9_]{0,62}$'",
            name="ck_operation_journal_action",
        ),
        CheckConstraint(
            "jsonb_typeof(resources) = 'array' "
            "AND jsonb_array_length(resources) BETWEEN 1 AND 100",
            name="ck_operation_journal_resources",
        ),
        CheckConstraint(
            "(causation_id IS NULL AND operation_id = correlation_id) OR "
            "(causation_id IS NOT NULL "
            "AND operation_id <> correlation_id "
            "AND operation_id <> causation_id)",
            name="ck_operation_journal_trace",
        ),
        CheckConstraint(
            "created_at = updated_at",
            name="ck_operation_journal_append_only_timestamp",
        ),
        {"schema": "scholens"},
    )

    entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
    )
    operation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    correlation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    causation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    initiated_by: Mapped[str] = mapped_column(String(16), nullable=False)
    origin_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    origin_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    origin_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    turn_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(127), nullable=False)
    resources: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)


__all__ = ["OperationJournalEntryModel"]
