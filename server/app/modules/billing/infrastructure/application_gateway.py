"""Concrete SQLAlchemy, Stripe, telemetry, and email billing adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import stripe
from app.database.telemetry import track_event
from app.helpers.email import notify_converted_billing_interval
from app.modules.billing.application.contracts import UsageResponse
from app.modules.billing.application.ports import (
    BillingEvents,
    BillingNotifier,
    BillingPaymentFailed,
    BillingProviderUnavailable,
    PaymentProvider,
    ProviderCheckoutSession,
    ProviderSchedule,
    ProviderSubscription,
    SubscriptionRecord,
    SubscriptionStore,
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
        user_id=int(model.user_id),
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

    def save(self, user_id: int, **changes: object) -> SubscriptionRecord:
        model = subscription_repository.create_or_update(self._db, user_id, changes)
        return _record(model)

    def refresh_from_provider(
        self, provider_subscription: ProviderSubscription
    ) -> SubscriptionRecord | None:
        model = subscription_repository.update_subscription_status(
            self._db,
            provider_subscription.subscription_id,
            provider_subscription.status,
            stripe_price_id=provider_subscription.price_id,
            period_start=provider_subscription.current_period_start,
            period_end=provider_subscription.current_period_end,
            cancel_at_period_end=provider_subscription.cancel_at_period_end,
        )
        return _record(model) if model else None


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
        params: dict[str, object] = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            "metadata": {"user_id": str(user_id)},
        }
        if payment_method_id:
            params["default_payment_method"] = payment_method_id
        try:
            value = stripe.Subscription.create(**params)  # type: ignore[arg-type]
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
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self, event_name: str, *, actor: Actor, properties: dict[str, object]
    ) -> None:
        track_event(
            event_name=event_name,
            properties=properties,
            user_id=str(actor.id),
            db=self._db,
        )


class EmailBillingNotifier(BillingNotifier):
    def interval_change_scheduled(self, *, actor: Actor, new_interval: str) -> None:
        notify_converted_billing_interval(
            email=actor.email,
            new_interval=new_interval,
            name=actor.display_name,
        )
