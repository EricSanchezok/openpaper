from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    func,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import (
    SubscriptionPlan,
    SubscriptionStatus,
    StripeWebhookEventStatus,
)

if TYPE_CHECKING:
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
