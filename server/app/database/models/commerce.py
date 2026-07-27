from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    func,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, JsonValue
from .enums import (
    JobStatus,
    SubscriptionPlan,
    SubscriptionStatus,
    StripeWebhookEventStatus,
)

if TYPE_CHECKING:
    from .content import Document
    from .identity import AuthUser
    from .projects import Project


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Subscription details
    plan: Mapped[str] = mapped_column(
        String, nullable=False, default=SubscriptionPlan.BASIC
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=SubscriptionStatus.ACTIVE
    )

    # Billing period
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Stripe integration fields
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_price_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Cancel at period end flag
    cancel_at_period_end: Mapped[bool | None] = mapped_column(Boolean, default=False)

    # Stripe Subscription Schedule ID (for deferred interval changes)
    stripe_schedule_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # When the subscription was canceled, if it was
    canceled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="subscription")


class StripeWebhookEvent(Base):
    """Minimal, non-PII ledger for reliable Stripe webhook processing."""

    __tablename__ = "stripe_webhook_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=StripeWebhookEventStatus.PROCESSING,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'ignored')",
            name="ck_stripe_webhook_events_status",
        ),
    )


class Onboarding(Base):
    __tablename__ = "onboarding"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    # Basic user information
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True)

    # Research fields (stored as comma-separated string)
    research_fields: Mapped[str | None] = mapped_column(String, nullable=True)
    research_fields_other: Mapped[str | None] = mapped_column(String, nullable=True)

    # Job titles (stored as comma-separated string)
    job_titles: Mapped[str | None] = mapped_column(String, nullable=True)
    job_titles_other: Mapped[str | None] = mapped_column(String, nullable=True)

    # Reading frequency
    reading_frequency: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="onboarding")


class DataTableExtractionJob(Base):
    __tablename__ = "data_table_extraction_jobs"
    __table_args__ = (
        CheckConstraint(
            "NOT is_shared OR project_id IS NOT NULL",
            name="ck_data_table_jobs_shared_project",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )

    columns: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )  # Columns to extract

    task_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # For tracking task in Celery

    status: Mapped[str] = mapped_column(
        String, nullable=False, default=JobStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    user: Mapped["AuthUser | None"] = relationship(
        "AuthUser", back_populates="data_table_jobs"
    )
    project: Mapped["Project | None"] = relationship("Project")

    # Relationship to results
    result: Mapped["DataTableExtractionResult | None"] = relationship(
        "DataTableExtractionResult",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )


class DataTableExtractionResult(Base):
    """
    Stores the result of a data table extraction job.
    Contains the columns extracted and links to individual row results.
    """

    __tablename__ = "data_table_extraction_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_table_extraction_jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    columns: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False
    )  # List of column names
    row_failures: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=list
    )  # List of paper IDs that failed

    job: Mapped["DataTableExtractionJob"] = relationship(
        "DataTableExtractionJob", back_populates="result"
    )
    rows: Mapped[list["DataTableRow"]] = relationship(
        "DataTableRow",
        back_populates="data_table",
        cascade="all, delete-orphan",
    )


class DataTableRow(Base):
    """
    Stores a single row of extracted data for a paper.
    The 'values' field is JSONB containing: {column_name: {value: str, citations: [{text, index}]}}
    """

    __tablename__ = "data_table_rows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    data_table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("data_table_extraction_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    values: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    # values schema: {
    #   "column_name": {
    #     "value": "extracted value",
    #     "citations": [{"text": "citation text", "index": 1}, ...]
    #   }
    # }

    data_table: Mapped["DataTableExtractionResult"] = relationship(
        "DataTableExtractionResult", back_populates="rows"
    )
    paper: Mapped["Document"] = relationship("Document")

    # Index for efficient lookups by paper
    __table_args__ = (
        Index("ix_data_table_rows_paper_id", "paper_id"),
        Index("ix_data_table_rows_data_table_id", "data_table_id"),
    )
