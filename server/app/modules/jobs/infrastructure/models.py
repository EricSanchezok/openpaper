"""Durable background work and transactional broker dispatch."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.shared.domain import JsonValue
from app.shared.infrastructure.persistence import Base
from app.shared.domain.enums import JobDispatchStatus, JobStatus

if TYPE_CHECKING:
    from app.modules.papers.infrastructure.models import Document
    from app.modules.identity.infrastructure.models import AuthUser
    from app.modules.projects.infrastructure.models import Project


class DurableJob(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_jobs_idempotency_key"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_jobs_status",
        ),
        Index("ix_jobs_requester_activity", "requested_by_id", "created_at"),
        Index("ix_jobs_project_status", "project_id", "status"),
        Index("ix_jobs_document_status", "document_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    origin_operation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=JobStatus.PENDING.value,
        server_default=JobStatus.PENDING.value,
    )
    progress_message: Mapped[str | None] = mapped_column(
        String(240),
        nullable=True,
    )
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    requested_by: Mapped["AuthUser | None"] = relationship("AuthUser")
    project: Mapped["Project | None"] = relationship("Project")
    document: Mapped["Document | None"] = relationship("Document")
    dispatch: Mapped["JobDispatch | None"] = relationship(
        "JobDispatch",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )


class JobDispatch(Base):
    __tablename__ = "job_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'publishing', 'published')",
            name="ck_job_dispatches_status",
        ),
        Index(
            "ix_job_dispatches_pending",
            "status",
            "available_at",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    queue: Mapped[str] = mapped_column(String(80), nullable=False)
    kwargs: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=JobDispatchStatus.PENDING.value,
        server_default=JobDispatchStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )
    last_error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["DurableJob"] = relationship(
        "DurableJob",
        back_populates="dispatch",
    )


class JobsWebhookNonce(Base):
    """Consumed Jobs request nonce; the primary key prevents replay."""

    __tablename__ = "jobs_webhook_nonces"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)


__all__ = ["DurableJob", "JobDispatch"]
