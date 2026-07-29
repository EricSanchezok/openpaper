"""Billing use cases independent from HTTP, SQLAlchemy, and Stripe."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import NoReturn

from app.modules.billing.application.contracts import (
    CheckoutSessionResponse,
    CheckoutSessionStatusResponse,
    IntervalChangeResponse,
    PortalSessionResponse,
    ScheduledIntervalChange,
    SubscriptionActionResponse,
    SubscriptionInterval,
    SubscriptionResponse,
    SubscriptionSummary,
    UsageResponse,
)
from app.modules.billing.application.ports import (
    BillingEvents,
    BillingNotifier,
    BillingPaymentFailed,
    BillingProviderUnavailable,
    PaymentProvider,
    SubscriptionStore,
    UsageReader,
)
from app.shared.application import Actor
from app.shared.domain import AppError

logger = logging.getLogger(__name__)


class Billing:
    """The public application API for account billing."""

    def __init__(
        self,
        *,
        subscriptions: SubscriptionStore,
        payments: PaymentProvider,
        usage: UsageReader,
        events: BillingEvents,
        notifier: BillingNotifier,
        monthly_price_id: str | None,
        yearly_price_id: str | None,
    ) -> None:
        self._subscriptions = subscriptions
        self._payments = payments
        self._usage = usage
        self._events = events
        self._notifier = notifier
        self._price_ids = {
            SubscriptionInterval.MONTHLY: monthly_price_id,
            SubscriptionInterval.YEARLY: yearly_price_id,
        }

    def create_checkout(
        self, actor: Actor, interval: SubscriptionInterval
    ) -> CheckoutSessionResponse:
        subscription = self._subscriptions.get(actor.id)
        if subscription and subscription.status in {
            "active",
            "past_due",
            "trialing",
        }:
            raise AppError(
                code="subscription_already_active",
                message="Use the customer portal to manage the active subscription",
                status_code=400,
            )

        if (
            subscription
            and subscription.status == "incomplete"
            and subscription.stripe_subscription_id
        ):
            try:
                self._payments.cancel_subscription(subscription.stripe_subscription_id)
            except BillingProviderUnavailable:
                logger.warning(
                    "Could not cancel incomplete subscription %s",
                    subscription.stripe_subscription_id,
                    exc_info=True,
                )

        price_id = self._required_price(interval)
        customer_id = subscription.stripe_customer_id if subscription else None
        if not customer_id:
            try:
                customer_id = self._payments.create_customer(actor)
            except BillingProviderUnavailable as exc:
                self._provider_error("stripe_checkout_failed", exc)
            self._subscriptions.save(actor.id, stripe_customer_id=customer_id)

        self._events.record(
            "checkout_initiated",
            actor=actor,
            properties={"interval": interval.value},
        )
        try:
            checkout = self._payments.create_checkout_session(
                user_id=actor.id,
                customer_id=customer_id,
                price_id=price_id,
            )
        except BillingProviderUnavailable as exc:
            self._provider_error("stripe_checkout_failed", exc)
        return CheckoutSessionResponse(client_secret=checkout.client_secret)

    def checkout_status(self, session_id: str) -> CheckoutSessionStatusResponse:
        try:
            checkout = self._payments.get_checkout_session(session_id)
        except BillingProviderUnavailable as exc:
            raise AppError(
                code="stripe_session_unavailable",
                message="The checkout session could not be retrieved",
                status_code=502,
            ) from exc

        backend_found = False
        backend_status = None
        if checkout.status == "complete" and checkout.client_reference_id:
            try:
                user_id = int(checkout.client_reference_id)
            except ValueError:
                logger.warning(
                    "Invalid checkout client reference %r",
                    checkout.client_reference_id,
                )
            else:
                subscription = self._subscriptions.get(user_id)
                if subscription and subscription.stripe_subscription_id:
                    backend_found = True
                    backend_status = subscription.status or "unknown"
                    if (
                        checkout.subscription_id
                        and subscription.stripe_subscription_id
                        != checkout.subscription_id
                    ):
                        logger.warning(
                            "Checkout/backend subscription mismatch for user %s",
                            user_id,
                        )
        return CheckoutSessionStatusResponse(
            status=checkout.status,
            customer_email=checkout.customer_email,
            backend_subscription_found=backend_found,
            backend_subscription_status=backend_status,
        )

    def get_subscription(self, actor: Actor) -> SubscriptionResponse:
        subscription = self._subscriptions.get(actor.id)
        if not subscription:
            return SubscriptionResponse(has_subscription=False)

        interval = self._interval_for_price(subscription.stripe_price_id)
        if subscription.stripe_subscription_id:
            try:
                provider_subscription = self._payments.get_subscription(
                    subscription.stripe_subscription_id
                )
            except BillingProviderUnavailable:
                logger.warning(
                    "Provider subscription refresh failed; using local state",
                    exc_info=True,
                )
            else:
                if self._interval_for_price(provider_subscription.price_id) is None:
                    return SubscriptionResponse(has_subscription=False)
                refreshed = self._subscriptions.refresh_from_provider(
                    provider_subscription
                )
                if refreshed:
                    subscription = refreshed
                    interval = self._interval_for_price(provider_subscription.price_id)

        period_end = subscription.current_period_end
        is_valid = bool(period_end and period_end > datetime.now(tz=timezone.utc))
        status = subscription.status or "inactive"
        scheduled_change = None
        if subscription.stripe_schedule_id and interval:
            scheduled_change = ScheduledIntervalChange(
                new_interval=(
                    SubscriptionInterval.YEARLY
                    if interval == SubscriptionInterval.MONTHLY
                    else SubscriptionInterval.MONTHLY
                ),
                effective_date=period_end,
            )
        return SubscriptionResponse(
            has_subscription=is_valid,
            had_subscription=subscription.stripe_subscription_id is not None,
            requires_payment_update=status in {"past_due", "unpaid", "incomplete"},
            subscription=SubscriptionSummary(
                status=status,
                interval=interval,
                current_period_start=subscription.current_period_start,
                current_period_end=period_end,
                cancel_at_period_end=subscription.cancel_at_period_end,
            ),
            scheduled_change=scheduled_change,
        )

    def get_usage(self, actor: Actor) -> UsageResponse:
        return self._usage.read(actor)

    def create_portal(self, actor: Actor) -> PortalSessionResponse:
        subscription = self._subscriptions.get(actor.id)
        if not subscription or not subscription.stripe_customer_id:
            raise AppError(
                code="stripe_customer_not_found",
                message="No billing account is available for this user",
                status_code=400,
            )
        try:
            url = self._payments.create_portal_session(subscription.stripe_customer_id)
        except BillingProviderUnavailable as exc:
            self._provider_error("stripe_portal_failed", exc)
        return PortalSessionResponse(url=url)

    def resume(self, actor: Actor) -> SubscriptionActionResponse:
        subscription = self._subscriptions.get(actor.id)
        missing = self._missing_subscription_result(subscription)
        if missing:
            return missing
        assert subscription is not None
        assert subscription.stripe_customer_id
        assert subscription.stripe_subscription_id

        try:
            provider_subscription = self._payments.get_subscription(
                subscription.stripe_subscription_id
            )
            if provider_subscription.status == "canceled":
                payment_method_id = self._payments.get_default_payment_method(
                    customer_id=subscription.stripe_customer_id,
                    subscription=provider_subscription,
                )
                if not payment_method_id:
                    return self._checkout_redirect("no_payment_method")
                if not subscription.stripe_price_id:
                    return self._checkout_redirect("no_price_id")
                created = self._payments.create_subscription(
                    user_id=actor.id,
                    customer_id=subscription.stripe_customer_id,
                    price_id=subscription.stripe_price_id,
                    payment_method_id=payment_method_id,
                )
                self._events.record(
                    "subscription_reactivated_new",
                    actor=actor,
                    properties={
                        "old_subscription_id": subscription.stripe_subscription_id,
                        "new_subscription_id": created.subscription_id,
                        "customer_id": subscription.stripe_customer_id,
                        "interval": (
                            self._interval_for_price(subscription.stripe_price_id)
                            or "unknown"
                        ),
                    },
                )
                return SubscriptionActionResponse(
                    success=True, subscription_id=created.subscription_id
                )

            if provider_subscription.cancel_at_period_end:
                self._payments.resume_subscription(subscription.stripe_subscription_id)
                self._events.record(
                    "subscription_cancellation_reversed",
                    actor=actor,
                    properties={
                        "subscription_id": subscription.stripe_subscription_id,
                        "customer_id": subscription.stripe_customer_id,
                    },
                )
                return SubscriptionActionResponse(
                    success=True,
                    subscription_id=subscription.stripe_subscription_id,
                    action="cancellation_reversed",
                    message=(
                        "Your subscription cancellation has been reversed "
                        "and will continue."
                    ),
                )
            return SubscriptionActionResponse(
                success=True,
                subscription_id=subscription.stripe_subscription_id,
                action="no_action",
                message="Your subscription is still active.",
            )
        except BillingPaymentFailed:
            return self._checkout_redirect("payment_failed")
        except BillingProviderUnavailable:
            return SubscriptionActionResponse(
                success=False,
                error="Previous subscription not found in billing provider",
            )

    def schedule_interval_change(
        self, actor: Actor, new_interval: SubscriptionInterval
    ) -> IntervalChangeResponse:
        subscription = self._subscriptions.get(actor.id)
        if not subscription:
            return IntervalChangeResponse(
                success=False, error="No existing subscription found"
            )
        if not subscription.stripe_subscription_id:
            return IntervalChangeResponse(
                success=False, error="No billing subscription ID found"
            )
        new_price_id = self._required_price(new_interval)
        try:
            provider_subscription = self._payments.get_subscription(
                subscription.stripe_subscription_id
            )
            if provider_subscription.status not in {"active", "trialing"}:
                raise AppError(
                    code="subscription_interval_unavailable",
                    message=(
                        "The billing interval cannot be changed for this subscription"
                    ),
                    status_code=400,
                )
            current_price_id = provider_subscription.price_id
            if not current_price_id:
                raise AppError(
                    code="subscription_price_unavailable",
                    message="The current subscription price is unavailable",
                    status_code=409,
                )
            if current_price_id == new_price_id:
                return IntervalChangeResponse(
                    success=False,
                    message=(
                        f"Subscription is already on {new_interval.value}ly billing"
                    ),
                )
            if subscription.stripe_schedule_id:
                self._payments.release_schedule(subscription.stripe_schedule_id)
            schedule = self._payments.create_schedule(
                subscription.stripe_subscription_id
            )
            self._payments.configure_interval_change(
                schedule=schedule,
                current_price_id=current_price_id,
                new_price_id=new_price_id,
            )
        except BillingProviderUnavailable as exc:
            raise AppError(
                code="subscription_interval_failed",
                message=("The subscription interval change could not be scheduled"),
                status_code=502,
            ) from exc

        self._subscriptions.save(actor.id, stripe_schedule_id=schedule.schedule_id)
        effective_date = provider_subscription.current_period_end
        if effective_date is None:
            effective_date = datetime.fromtimestamp(
                schedule.current_phase_end, tz=timezone.utc
            )
        self._events.record(
            "subscription_interval_scheduled",
            actor=actor,
            properties={
                "subscription_id": subscription.stripe_subscription_id,
                "schedule_id": schedule.schedule_id,
                "old_interval": (
                    self._interval_for_price(current_price_id) or "unknown"
                ),
                "new_interval": new_interval.value,
                "effective_date": effective_date.isoformat(),
            },
        )
        self._notifier.interval_change_scheduled(
            actor=actor, new_interval=new_interval.value
        )
        return IntervalChangeResponse(
            success=True,
            message=(
                f"Subscription interval will change to "
                f"{new_interval.value}ly on "
                f"{effective_date.strftime('%B %d, %Y')}"
            ),
            scheduled_date=effective_date,
            new_interval=new_interval,
        )

    def cancel_interval_change(self, actor: Actor) -> IntervalChangeResponse:
        subscription = self._subscriptions.get(actor.id)
        if not subscription:
            return IntervalChangeResponse(
                success=False, error="No existing subscription found"
            )
        if not subscription.stripe_schedule_id:
            return IntervalChangeResponse(
                success=False, error="No scheduled change found"
            )
        try:
            self._payments.release_schedule(subscription.stripe_schedule_id)
        except BillingProviderUnavailable as exc:
            raise AppError(
                code="subscription_schedule_cancel_failed",
                message=("The scheduled subscription change could not be canceled"),
                status_code=502,
            ) from exc
        self._subscriptions.save(actor.id, stripe_schedule_id=None)
        self._events.record(
            "subscription_interval_schedule_canceled",
            actor=actor,
            properties={
                "subscription_id": subscription.stripe_subscription_id or "",
                "schedule_id": subscription.stripe_schedule_id,
            },
        )
        return IntervalChangeResponse(
            success=True,
            message="Scheduled billing change has been canceled",
        )

    def _required_price(self, interval: SubscriptionInterval) -> str:
        price_id = self._price_ids[interval]
        if not price_id:
            raise AppError(
                code="stripe_price_not_configured",
                message="Subscription billing is not configured",
                status_code=503,
            )
        return price_id

    def _interval_for_price(self, price_id: str | None) -> SubscriptionInterval | None:
        if price_id and price_id == self._price_ids[SubscriptionInterval.MONTHLY]:
            return SubscriptionInterval.MONTHLY
        if price_id and price_id == self._price_ids[SubscriptionInterval.YEARLY]:
            return SubscriptionInterval.YEARLY
        return None

    @staticmethod
    def _checkout_redirect(error: str) -> SubscriptionActionResponse:
        messages = {
            "no_payment_method": (
                "No payment method is available. Use checkout to add one "
                "and resubscribe."
            ),
            "payment_failed": (
                "Your payment method was declined. Update it and try again."
            ),
            "no_price_id": (
                "No price is associated with the subscription. Contact support."
            ),
        }
        return SubscriptionActionResponse(
            success=False,
            error=error,
            message=messages[error],
            redirect_to_checkout=True,
        )

    @staticmethod
    def _missing_subscription_result(
        subscription: object | None,
    ) -> SubscriptionActionResponse | None:
        if subscription is None:
            return SubscriptionActionResponse(
                success=False,
                error=(
                    "No existing subscription found. Create a new subscription instead."
                ),
            )
        record = subscription
        if not getattr(record, "stripe_customer_id"):
            return SubscriptionActionResponse(
                success=False,
                error="No billing customer exists. Use checkout instead.",
            )
        if not getattr(record, "stripe_subscription_id"):
            return SubscriptionActionResponse(
                success=False,
                error="No billing subscription exists. Use checkout instead.",
            )
        return None

    @staticmethod
    def _provider_error(code: str, exc: Exception) -> NoReturn:
        messages = {
            "stripe_checkout_failed": ("The checkout session could not be created"),
            "stripe_portal_failed": "The billing portal could not be opened",
        }
        raise AppError(code=code, message=messages[code], status_code=502) from exc
