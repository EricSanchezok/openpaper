"""Concrete SQLAlchemy, Stripe, telemetry, and email billing adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import stripe
from app.database.telemetry import track_event
from app.helpers.email import notify_converted_billing_interval
from app.modules.billing.application.contracts import UsageResponse
from app.modules.billing.application.ports import (
    BillingEvent,
    BillingEvents,
    BillingIssueNotification,
    BillingNotification,
    BillingNotifier,
    BillingPaymentFailed,
    BillingProviderUnavailable,
    CancellationConfirmedNotification,
    IntervalChangeScheduledNotification,
    PaymentProvider,
    ProviderCheckoutSession,
    ProviderSchedule,
    ProviderSubscription,
    SubscriptionRecord,
    SubscriptionStore,
    SubscriptionWelcomeNotification,
    SubscriptionWriteResult,
    UsageReader,
)
from app.modules.billing.infrastructure.config import YOUR_DOMAIN
from app.modules.billing.infrastructure.quotas import get_user_usage_info
from app.modules.billing.infrastructure.subscription_repository import (
    subscription_repository,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


def _record(model: Any) -> SubscriptionRecord:
    return SubscriptionRecord(
        id=model.id,
        user_id=int(model.user_id),
        plan=str(model.plan),
        stripe_customer_id=model.stripe_customer_id,
        stripe_subscription_id=model.stripe_subscription_id,
        stripe_price_id=model.stripe_price_id,
        stripe_schedule_id=model.stripe_schedule_id,
        status=str(model.status) if model.status else None,
        current_period_start=model.current_period_start,
        current_period_end=model.current_period_end,
        cancel_at_period_end=bool(model.cancel_at_period_end),
    )


class SqlAlchemySubscriptionStore(SubscriptionStore):
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, user_id: int) -> SubscriptionRecord | None:
        model = subscription_repository.get_by_user_id(self._db, user_id)
        return _record(model) if model else None

    def get_by_customer_id(self, customer_id: str) -> SubscriptionRecord | None:
        model = subscription_repository.get_by_stripe_customer_id(
            self._db,
            customer_id,
        )
        return _record(model) if model else None

    def get_by_subscription_id(
        self,
        subscription_id: str,
    ) -> SubscriptionRecord | None:
        model = subscription_repository.get_by_stripe_subscription_id(
            self._db,
            subscription_id,
        )
        return _record(model) if model else None

    def save(self, user_id: int, **changes: object) -> SubscriptionWriteResult:
        existing = subscription_repository.get_by_user_id(self._db, user_id)
        if existing is not None:
            applied = {
                key: value
                for key, value in changes.items()
                if getattr(existing, key) != value
            }
            if not applied:
                return SubscriptionWriteResult(
                    record=_record(existing),
                    changed=False,
                )
            model = subscription_repository.create_or_update(
                self._db,
                user_id,
                applied,
            )
            return SubscriptionWriteResult(
                record=_record(model),
                changed=True,
            )
        model = subscription_repository.create_or_update(self._db, user_id, changes)
        return SubscriptionWriteResult(
            record=_record(model),
            changed=True,
        )


class StripePaymentProvider(PaymentProvider):
    @staticmethod
    def _subscription(value: Any) -> ProviderSubscription:
        items = value["items"]["data"] if value.get("items") else []
        item = items[0] if items else None
        price = item.get("price") if item else None
        period_start = item.get("current_period_start") if item else None
        period_end = item.get("current_period_end") if item else None
        return ProviderSubscription(
            subscription_id=str(value.id),
            status=str(value.status),
            price_id=str(price.id) if price and price.id else None,
            current_period_start=(
                datetime.fromtimestamp(period_start, tz=timezone.utc)
                if period_start
                else None
            ),
            current_period_end=(
                datetime.fromtimestamp(period_end, tz=timezone.utc)
                if period_end
                else None
            ),
            cancel_at_period_end=bool(value.cancel_at_period_end),
            default_payment_method_id=(
                str(value.default_payment_method)
                if value.default_payment_method
                else None
            ),
        )

    def cancel_subscription(self, subscription_id: str) -> None:
        try:
            stripe.Subscription.cancel(subscription_id)
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc

    def create_customer(self, actor: Actor) -> str:
        try:
            customer = stripe.Customer.create(
                email=actor.email,
                name=actor.display_name or actor.email,
                metadata={"user_id": str(actor.id)},
            )
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc
        return str(customer.id)

    def create_checkout_session(
        self,
        *,
        user_id: int,
        customer_id: str,
        price_id: str,
    ) -> ProviderCheckoutSession:
        try:
            session = stripe.checkout.Session.create(
                ui_mode="embedded",
                client_reference_id=str(user_id),
                line_items=[{"quantity": 1, "price": price_id}],
                mode="subscription",
                allow_promotion_codes=True,
                return_url=(
                    f"{YOUR_DOMAIN}/subscribed?session_id={{CHECKOUT_SESSION_ID}}"
                ),
                customer=customer_id,
            )
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc
        return ProviderCheckoutSession(
            session_id=str(session.id),
            status=str(session.status or "open"),
            client_secret=session.client_secret,
        )

    def get_checkout_session(self, session_id: str) -> ProviderCheckoutSession:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc
        details = session.customer_details
        return ProviderCheckoutSession(
            session_id=str(session.id),
            status=str(session.status),
            customer_email=details.email if details else None,
            client_reference_id=session.client_reference_id,
            subscription_id=(
                str(session.subscription) if session.subscription else None
            ),
        )

    def get_subscription(self, subscription_id: str) -> ProviderSubscription:
        try:
            value = stripe.Subscription.retrieve(subscription_id)
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc
        return self._subscription(value)

    def create_portal_session(self, customer_id: str) -> str:
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=f"{YOUR_DOMAIN}/pricing",
            )
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc
        return str(session.url)

    def get_default_payment_method(
        self,
        *,
        customer_id: str,
        subscription: ProviderSubscription,
    ) -> str | None:
        try:
            customer = stripe.Customer.retrieve(customer_id)
            invoice_settings = customer.invoice_settings
            if invoice_settings and invoice_settings.default_payment_method:
                return str(invoice_settings.default_payment_method)
            if subscription.default_payment_method_id:
                return subscription.default_payment_method_id
            methods = stripe.PaymentMethod.list(customer=customer_id, type="card")
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc
        return str(methods.data[0].id) if methods.data else None

    def create_subscription(
        self,
        *,
        user_id: int,
        customer_id: str,
        price_id: str,
        payment_method_id: str | None,
    ) -> ProviderSubscription:
        try:
            if payment_method_id:
                value = stripe.Subscription.create(
                    customer=customer_id,
                    items=[{"price": price_id}],
                    metadata={"user_id": str(user_id)},
                    default_payment_method=payment_method_id,
                )
            else:
                value = stripe.Subscription.create(
                    customer=customer_id,
                    items=[{"price": price_id}],
                    metadata={"user_id": str(user_id)},
                )
        except stripe.StripeError as exc:
            message = str(exc).lower()
            if any(
                marker in message
                for marker in (
                    "card",
                    "declined",
                    "insufficient",
                    "payment",
                    "payment source",
                )
            ):
                raise BillingPaymentFailed from exc
            raise BillingProviderUnavailable from exc
        return self._subscription(value)

    def resume_subscription(self, subscription_id: str) -> None:
        try:
            stripe.Subscription.modify(subscription_id, cancel_at_period_end=False)
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc

    def release_schedule(self, schedule_id: str) -> None:
        try:
            stripe.SubscriptionSchedule.release(schedule_id)
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc

    def create_schedule(self, subscription_id: str) -> ProviderSchedule:
        try:
            schedule = stripe.SubscriptionSchedule.create(
                from_subscription=subscription_id
            )
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc
        phase = schedule.phases[0]
        return ProviderSchedule(
            schedule_id=str(schedule.id),
            current_phase_start=int(phase.start_date),
            current_phase_end=int(phase.end_date),
        )

    def configure_interval_change(
        self,
        *,
        schedule: ProviderSchedule,
        current_price_id: str,
        new_price_id: str,
    ) -> None:
        try:
            stripe.SubscriptionSchedule.modify(
                schedule.schedule_id,
                end_behavior="release",
                phases=[
                    {
                        "items": [{"price": current_price_id, "quantity": 1}],
                        "start_date": schedule.current_phase_start,
                        "end_date": schedule.current_phase_end,
                    },
                    {
                        "items": [{"price": new_price_id, "quantity": 1}],
                    },
                ],
            )
        except stripe.StripeError as exc:
            raise BillingProviderUnavailable from exc


class SqlAlchemyUsageReader(UsageReader):
    def __init__(self, db: Session) -> None:
        self._db = db

    def read(self, actor: Actor) -> UsageResponse:
        return UsageResponse.model_validate(get_user_usage_info(self._db, actor))


class PostHogBillingEvents(BillingEvents):
    def record(self, event: BillingEvent) -> None:
        track_event(
            event_name=event.name,
            properties=dict(event.properties),
            user_id=str(event.actor_id) if event.actor_id is not None else None,
        )


class EmailBillingNotifier(BillingNotifier):
    def send(self, notification: BillingNotification) -> None:
        if isinstance(notification, IntervalChangeScheduledNotification):
            notify_converted_billing_interval(
                email=notification.email,
                new_interval=notification.new_interval,
                name=notification.display_name,
            )
            return
        if isinstance(notification, SubscriptionWelcomeNotification):
            from app.helpers.email import send_subscription_welcome_email

            send_subscription_welcome_email(notification.email)
            return
        if isinstance(notification, CancellationConfirmedNotification):
            from app.helpers.email import send_confirmation_cancellation_email

            first_name = (
                notification.display_name.split(" ")[0]
                if notification.display_name
                else None
            )
            send_confirmation_cancellation_email(
                to_email=notification.email,
                name=first_name,
            )
            return
        if isinstance(notification, BillingIssueNotification):
            from app.helpers.email import notify_billing_issue

            notify_billing_issue(
                notification.email,
                notification.issue,
                notification.display_name,
            )
            return
        raise TypeError(f"Unsupported billing notification: {type(notification)!r}")
