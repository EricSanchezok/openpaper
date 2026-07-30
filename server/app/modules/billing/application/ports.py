"""Replaceable billing persistence, provider, and notification boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Mapping, Protocol
from uuid import UUID

from app.modules.billing.application.contracts import UsageResponse
from app.shared.application import Actor


class BillingProviderUnavailable(Exception):
    """The payment provider could not complete an operation."""


class BillingPaymentFailed(BillingProviderUnavailable):
    """A payment method was missing or declined."""


@dataclass(frozen=True, slots=True)
class SubscriptionRecord:
    id: UUID
    user_id: int
    plan: str
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    stripe_price_id: str | None
    stripe_schedule_id: str | None
    status: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool


@dataclass(frozen=True, slots=True)
class SubscriptionWriteResult:
    record: SubscriptionRecord
    changed: bool


@dataclass(frozen=True, slots=True)
class ProviderSubscription:
    subscription_id: str
    status: str
    price_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    default_payment_method_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderCheckoutSession:
    session_id: str
    status: str
    client_secret: str | None = None
    customer_email: str | None = None
    client_reference_id: str | None = None
    subscription_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSchedule:
    schedule_id: str
    current_phase_start: int
    current_phase_end: int


class SubscriptionStore(Protocol):
    def get(self, user_id: int) -> SubscriptionRecord | None: ...

    def get_by_customer_id(self, customer_id: str) -> SubscriptionRecord | None: ...

    def get_by_subscription_id(
        self,
        subscription_id: str,
    ) -> SubscriptionRecord | None: ...

    def save(self, user_id: int, **changes: object) -> SubscriptionWriteResult: ...


class PaymentProvider(Protocol):
    def cancel_subscription(self, subscription_id: str) -> None: ...

    def create_customer(self, actor: Actor) -> str: ...

    def create_checkout_session(
        self,
        *,
        user_id: int,
        customer_id: str,
        price_id: str,
    ) -> ProviderCheckoutSession: ...

    def get_checkout_session(self, session_id: str) -> ProviderCheckoutSession: ...

    def get_subscription(self, subscription_id: str) -> ProviderSubscription: ...

    def create_portal_session(self, customer_id: str) -> str: ...

    def get_default_payment_method(
        self,
        *,
        customer_id: str,
        subscription: ProviderSubscription,
    ) -> str | None: ...

    def create_subscription(
        self,
        *,
        user_id: int,
        customer_id: str,
        price_id: str,
        payment_method_id: str | None,
    ) -> ProviderSubscription: ...

    def resume_subscription(self, subscription_id: str) -> None: ...

    def release_schedule(self, schedule_id: str) -> None: ...

    def create_schedule(self, subscription_id: str) -> ProviderSchedule: ...

    def configure_interval_change(
        self,
        *,
        schedule: ProviderSchedule,
        current_price_id: str,
        new_price_id: str,
    ) -> None: ...


class UsageReader(Protocol):
    def read(self, actor: Actor) -> UsageResponse: ...


@dataclass(frozen=True, slots=True)
class BillingEvent:
    name: str
    actor_id: int | None
    properties: Mapping[str, object]


class BillingEvents(Protocol):
    def record(self, event: BillingEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class IntervalChangeScheduledNotification:
    email: str
    display_name: str | None
    new_interval: str
    kind: Literal["interval_change_scheduled"] = "interval_change_scheduled"


@dataclass(frozen=True, slots=True)
class SubscriptionWelcomeNotification:
    email: str
    display_name: str | None
    kind: Literal["subscription_welcome"] = "subscription_welcome"


@dataclass(frozen=True, slots=True)
class CancellationConfirmedNotification:
    email: str
    display_name: str | None
    kind: Literal["cancellation_confirmed"] = "cancellation_confirmed"


@dataclass(frozen=True, slots=True)
class BillingIssueNotification:
    email: str
    display_name: str | None
    issue: str
    kind: Literal["billing_issue"] = "billing_issue"


type BillingNotification = (
    IntervalChangeScheduledNotification
    | SubscriptionWelcomeNotification
    | CancellationConfirmedNotification
    | BillingIssueNotification
)


class BillingNotifier(Protocol):
    def send(self, notification: BillingNotification) -> None: ...
