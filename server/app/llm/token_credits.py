from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Iterator

from app.database.database import SessionLocal
from app.database.models import TokenUsageEvent, TokenWeeklyUsage
from app.schemas.user import CurrentUser
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class UsageContext:
    user_id: int
    feature: str
    operation_id: str


_usage_context: ContextVar[UsageContext | None] = ContextVar(
    "scholens_llm_usage_context", default=None
)


def utc_week_start(now: datetime | None = None) -> date:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return (current - timedelta(days=current.weekday())).date()


@contextmanager
def llm_usage_context(
    *, user_id: int, feature: str, operation_id: str | None = None
) -> Iterator[UsageContext]:
    context = UsageContext(
        user_id=user_id,
        feature=feature,
        operation_id=operation_id or str(uuid.uuid4()),
    )
    token = _usage_context.set(context)
    try:
        yield context
    finally:
        _usage_context.reset(token)


def current_usage_context() -> UsageContext | None:
    return _usage_context.get()


def settle_token_usage(
    *,
    model: str,
    reasoning_level: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    provider_request_id: str | None,
    reasoning_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int = 0,
    idempotency_key: str | None = None,
    status: str = "settled",
) -> bool:
    """Persist one provider-reported usage event and increment its weekly total once."""
    context = current_usage_context()
    if status not in {"settled", "unknown"}:
        raise ValueError("Unsupported token usage status")
    if context is None or (status == "settled" and total_tokens <= 0):
        return False

    week_start = utc_week_start()
    event_key = idempotency_key or f"{context.operation_id}:{uuid.uuid4()}"
    db = SessionLocal()
    try:
        event_stmt = (
            insert(TokenUsageEvent)
            .values(
                id=uuid.uuid4(),
                user_id=context.user_id,
                week_start=week_start,
                idempotency_key=event_key,
                operation_id=context.operation_id,
                feature=context.feature,
                provider="deepseek",
                model=model,
                reasoning_level=reasoning_level,
                provider_request_id=provider_request_id,
                prompt_tokens=max(0, prompt_tokens),
                completion_tokens=max(0, completion_tokens),
                reasoning_tokens=max(0, reasoning_tokens),
                cache_hit_tokens=max(0, cache_hit_tokens),
                cache_miss_tokens=max(0, cache_miss_tokens),
                total_tokens=total_tokens,
                status=status,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(TokenUsageEvent.id)
        )
        inserted = db.execute(event_stmt).scalar_one_or_none()
        if inserted is None:
            db.rollback()
            return False

        if status == "unknown":
            db.commit()
            return True

        weekly_stmt = (
            insert(TokenWeeklyUsage)
            .values(
                user_id=context.user_id,
                week_start=week_start,
                used_tokens=total_tokens,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "week_start"],
                set_={
                    "used_tokens": TokenWeeklyUsage.used_tokens + total_tokens,
                    "updated_at": datetime.now(UTC),
                },
            )
        )
        db.execute(weekly_stmt)
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_token_usage(db: Session, *, user_id: int) -> int:
    value = db.scalar(
        select(TokenWeeklyUsage.used_tokens).where(
            TokenWeeklyUsage.user_id == user_id,
            TokenWeeklyUsage.week_start == utc_week_start(),
        )
    )
    return int(value or 0)


def token_quota_status(db: Session, *, user: CurrentUser) -> tuple[int, int, int, int]:
    """Return (limit, used, remaining, overage) for the user's current plan."""
    from app.services.resource_quotas import (
        TOKEN_CREDITS_KEY,
        get_plan_limits,
        get_user_subscription_plan,
    )

    plan = get_user_subscription_plan(db, user)
    limit = int(get_plan_limits(plan)[TOKEN_CREDITS_KEY])
    used = get_token_usage(db, user_id=user.id)
    return limit, used, max(0, limit - used), max(0, used - limit)


def has_token_credits(db: Session, *, user: CurrentUser) -> bool:
    limit, used, _, _ = token_quota_status(db, user=user)
    return used < limit


__all__ = [
    "UsageContext",
    "current_usage_context",
    "get_token_usage",
    "has_token_credits",
    "llm_usage_context",
    "settle_token_usage",
    "token_quota_status",
    "utc_week_start",
]
