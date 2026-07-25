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
    ReferralAttributionMethod,
    ReferralStatus,
    SubscriptionPlan,
    SubscriptionStatus,
)

if TYPE_CHECKING:
    from .content import Paper, Project
    from .identity import AuthUser


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

    # Referral source
    referral_source: Mapped[str | None] = mapped_column(String, nullable=True)
    referral_source_other: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="onboarding")


class DiscoverSearch(Base):
    __tablename__ = "discover_searches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    subqueries: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    results: Mapped[dict[str, list[dict[str, JsonValue]]] | None] = mapped_column(
        JSONB, nullable=True
    )

    user: Mapped["AuthUser"] = relationship("AuthUser")


class DataTableExtractionJob(Base):
    __tablename__ = "data_table_extraction_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE"), nullable=True
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

    user: Mapped["AuthUser"] = relationship("AuthUser")
    project: Mapped["Project"] = relationship("Project")

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
    row_failures: Mapped[list[str] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=[]
    )  # List of paper IDs that failed

    job: Mapped["DataTableExtractionJob"] = relationship(
        "DataTableExtractionJob", back_populates="result"
    )
    rows: Mapped[list["DataTableRow"]] = relationship(
        "DataTableRow",
        back_populates="data_table",
        cascade="all, delete-orphan",
    )


class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    code: Mapped[str] = mapped_column(
        String(16), nullable=False, unique=True, index=True
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="referral_code")


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    referrer_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    referee_user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    code_used: Mapped[str] = mapped_column(String(16), nullable=False)
    attribution_method: Mapped[str] = mapped_column(
        String, nullable=False, default=ReferralAttributionMethod.LINK
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=ReferralStatus.ATTRIBUTED, index=True
    )

    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    credit_available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    referrer_credit_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=600
    )

    # Stripe coupon issued to the referee for 50% off their first month.
    referee_coupon_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Stripe Customer balance transaction created when credit becomes spendable.
    stripe_balance_transaction_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )

    fraud_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    referrer: Mapped["AuthUser"] = relationship(
        "AuthUser", foreign_keys=[referrer_user_id], back_populates="referrals_made"
    )
    referee: Mapped["AuthUser"] = relationship(
        "AuthUser", foreign_keys=[referee_user_id], back_populates="referral_received"
    )

    __table_args__ = (
        CheckConstraint(
            "referrer_user_id <> referee_user_id",
            name="check_referral_no_self_referral",
        ),
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
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    values: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, nullable=False, default={}
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
    paper: Mapped["Paper"] = relationship("Paper")

    # Index for efficient lookups by paper
    __table_args__ = (
        Index("ix_data_table_rows_paper_id", "paper_id"),
        Index("ix_data_table_rows_data_table_id", "data_table_id"),
    )
