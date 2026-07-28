from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import UUID, BigInteger, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TokenUsageEvent(Base):
    """Immutable provider usage returned by one DeepSeek API call."""

    __tablename__ = "token_usage_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_token_usage_idempotency_key"),
        Index("ix_token_usage_user_week", "user_id", "week_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="deepseek"
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    reasoning_level: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_miss_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="settled")


class TokenWeeklyUsage(Base):
    """Fast current-week aggregate; immutable usage events remain authoritative."""

    __tablename__ = "token_weekly_usage"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    used_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
