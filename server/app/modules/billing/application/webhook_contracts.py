"""Typed, provider-neutral subscription changes produced by a verified webhook."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class SubscriptionCreated:
    customer_id: str
    subscription_id: str
    price_id: str | None
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    kind: Literal["subscription_created"] = "subscription_created"


@dataclass(frozen=True, slots=True)
class SubscriptionUpdated:
    subscription_id: str
    price_id: str | None
    status: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    kind: Literal["subscription_updated"] = "subscription_updated"


@dataclass(frozen=True, slots=True)
class SubscriptionDeleted:
    subscription_id: str
    price_id: str | None
    kind: Literal["subscription_deleted"] = "subscription_deleted"


@dataclass(frozen=True, slots=True)
class SubscriptionStatusChanged:
    subscription_id: str
    status: str
    action: Literal[
        "payment_failed",
        "payment_succeeded",
        "subscription_past_due",
    ]
    kind: Literal["subscription_status_changed"] = "subscription_status_changed"


@dataclass(frozen=True, slots=True)
class SubscriptionScheduleCleared:
    subscription_id: str
    schedule_id: str
    kind: Literal["subscription_schedule_cleared"] = "subscription_schedule_cleared"


type BillingWebhookChange = (
    SubscriptionCreated
    | SubscriptionUpdated
    | SubscriptionDeleted
    | SubscriptionStatusChanged
    | SubscriptionScheduleCleared
)


@dataclass(frozen=True, slots=True)
class BillingWebhookResult:
    changed: bool
    cancellation_newly_scheduled: bool = False


__all__ = [
    "BillingWebhookChange",
    "BillingWebhookResult",
    "SubscriptionCreated",
    "SubscriptionDeleted",
    "SubscriptionScheduleCleared",
    "SubscriptionStatusChanged",
    "SubscriptionUpdated",
]
