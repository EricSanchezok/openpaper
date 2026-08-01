"""Short-transaction orchestration for Stripe-backed account billing."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, NoReturn

from app.modules.billing.application.billing import (
    IntervalChangePreparation,
    ResumePreparation,
)
from app.modules.billing.application.contracts import (
    CheckoutSessionResponse,
    CheckoutSessionStatusResponse,
    IntervalChangeResponse,
    PortalSessionResponse,
    SubscriptionActionResponse,
    SubscriptionInterval,
    SubscriptionResponse,
    UsageResponse,
)
from app.modules.billing.application.ports import (
    BillingEvent,
    BillingEvents,
    BillingNotification,
    BillingNotifier,
    BillingPaymentFailed,
    BillingProviderUnavailable,
    IntervalChangeScheduledNotification,
    PaymentProvider,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind

if TYPE_CHECKING:
    from app.bootstrap.capabilities import ApplicationCapabilities

logger = logging.getLogger(__name__)


class BillingWorkflow:
    """Run provider I/O between small query/command stages."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        payments: PaymentProvider,
        events: BillingEvents,
        notifier: BillingNotifier,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._payments = payments
        self._events = events
        self._notifier = notifier
        self._operation_factory = operation_factory

    def create_checkout(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        interval: SubscriptionInterval,
    ) -> CheckoutSessionResponse:
        prepared = self._executor.query(
            lambda capabilities: capabilities.billing.prepare_checkout(actor, interval)
        )
        subscription = prepared.subscription
        if (
            subscription
            and subscription.status == "incomplete"
            and subscription.stripe_subscription_id
        ):
            try:
                self._payments.cancel_subscription(subscription.stripe_subscription_id)
            except BillingProviderUnavailable:
                logger.warning(
                    "billing.incomplete_subscription.cancel_failed",
                    exc_info=True,
                )

        customer_id = subscription.stripe_customer_id if subscription else None
        if not customer_id:
            try:
                customer_id = self._payments.create_customer(actor)
            except BillingProviderUnavailable as exc:
                self._provider_error("stripe_checkout_failed", exc)
        try:
            checkout = self._payments.create_checkout_session(
                user_id=actor.id,
                customer_id=customer_id,
                price_id=prepared.price_id,
            )
        except BillingProviderUnavailable as exc:
            self._provider_error("stripe_checkout_failed", exc)

        complete_operation = self._child(operation)
        self._executor.command(
            lambda capabilities: capabilities.billing.complete_checkout(
                actor=actor,
                operation=complete_operation,
                customer_id=customer_id,
            )
        )
        self._record(
            BillingEvent(
                name="checkout_initiated",
                actor_id=actor.id,
                properties={"interval": interval.value},
            )
        )
        return CheckoutSessionResponse(client_secret=checkout.client_secret)

    def checkout_status(self, session_id: str) -> CheckoutSessionStatusResponse:
        try:
            checkout = self._payments.get_checkout_session(session_id)
        except BillingProviderUnavailable as exc:
            raise AppError(
                code="stripe_session_unavailable",
                message="The checkout session could not be retrieved",
                kind=FailureKind.DEPENDENCY_FAILURE,
            ) from exc
        return self._executor.query(
            lambda capabilities: capabilities.billing.checkout_status(checkout)
        )

    def get_subscription(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> SubscriptionResponse:
        local = self._executor.query(
            lambda capabilities: capabilities.billing.prepare_subscription_refresh(
                actor
            )
        )
        if local is None or not local.stripe_subscription_id:
            return self._executor.query(
                lambda capabilities: capabilities.billing.get_subscription(actor)
            )
        try:
            provider = self._payments.get_subscription(
                local.stripe_subscription_id,
            )
        except BillingProviderUnavailable:
            logger.warning(
                "billing.subscription_refresh.provider_failed",
                exc_info=True,
            )
            return self._executor.query(
                lambda capabilities: capabilities.billing.get_subscription(actor)
            )
        supported = self._executor.query(
            lambda capabilities: (
                capabilities.billing.interval_for_price(provider.price_id) is not None
            )
        )
        if not supported:
            return SubscriptionResponse(has_subscription=False)
        refresh_operation = self._child(operation)
        self._executor.command(
            lambda capabilities: capabilities.billing.complete_subscription_refresh(
                actor=actor,
                operation=refresh_operation,
                provider_subscription=provider,
            )
        )
        return self._executor.query(
            lambda capabilities: capabilities.billing.get_subscription(actor)
        )

    def get_usage(self, actor: Actor) -> UsageResponse:
        return self._executor.query(
            lambda capabilities: capabilities.billing.get_usage(actor)
        )

    def create_portal(self, actor: Actor) -> PortalSessionResponse:
        customer_id = self._executor.query(
            lambda capabilities: capabilities.billing.prepare_portal(actor)
        )
        try:
            url = self._payments.create_portal_session(customer_id)
        except BillingProviderUnavailable as exc:
            self._provider_error("stripe_portal_failed", exc)
        return PortalSessionResponse(url=url)

    def resume(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> SubscriptionActionResponse:
        prepared = self._executor.query(
            lambda capabilities: capabilities.billing.prepare_resume(actor)
        )
        if isinstance(prepared, SubscriptionActionResponse):
            return prepared
        assert isinstance(prepared, ResumePreparation)
        subscription = prepared.subscription
        assert subscription.stripe_customer_id
        assert subscription.stripe_subscription_id

        try:
            provider = self._payments.get_subscription(
                subscription.stripe_subscription_id
            )
            if provider.status == "canceled":
                payment_method_id = self._payments.get_default_payment_method(
                    customer_id=subscription.stripe_customer_id,
                    subscription=provider,
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
                complete_operation = self._child(operation)
                self._executor.command(
                    lambda capabilities: capabilities.billing.complete_new_subscription(
                        actor=actor,
                        operation=complete_operation,
                        provider_subscription=created,
                    )
                )
                interval = self._executor.query(
                    lambda capabilities: capabilities.billing.interval_for_price(
                        subscription.stripe_price_id
                    )
                )
                self._record(
                    BillingEvent(
                        name="subscription_reactivated_new",
                        actor_id=actor.id,
                        properties={
                            "old_subscription_id": (
                                subscription.stripe_subscription_id
                            ),
                            "new_subscription_id": created.subscription_id,
                            "customer_id": subscription.stripe_customer_id,
                            "interval": (
                                interval.value if interval is not None else "unknown"
                            ),
                        },
                    )
                )
                return SubscriptionActionResponse(
                    success=True,
                    subscription_id=created.subscription_id,
                )

            if provider.cancel_at_period_end:
                self._payments.resume_subscription(subscription.stripe_subscription_id)
                complete_operation = self._child(operation)
                self._executor.command(
                    lambda capabilities: (
                        capabilities.billing.complete_cancellation_reversal(
                            actor=actor,
                            operation=complete_operation,
                        )
                    )
                )
                self._record(
                    BillingEvent(
                        name="subscription_cancellation_reversed",
                        actor_id=actor.id,
                        properties={
                            "subscription_id": subscription.stripe_subscription_id,
                            "customer_id": subscription.stripe_customer_id,
                        },
                    )
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
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        new_interval: SubscriptionInterval,
    ) -> IntervalChangeResponse:
        prepared = self._executor.query(
            lambda capabilities: capabilities.billing.prepare_interval_change(
                actor,
                new_interval,
            )
        )
        if isinstance(prepared, IntervalChangeResponse):
            return prepared
        assert isinstance(prepared, IntervalChangePreparation)
        subscription = prepared.subscription
        assert subscription.stripe_subscription_id
        try:
            provider = self._payments.get_subscription(
                subscription.stripe_subscription_id
            )
            if provider.status not in {"active", "trialing"}:
                raise AppError(
                    code="subscription_interval_unavailable",
                    message=(
                        "The billing interval cannot be changed for this subscription"
                    ),
                    kind=FailureKind.INVALID_ARGUMENT,
                )
            current_price_id = provider.price_id
            if not current_price_id:
                raise AppError(
                    code="subscription_price_unavailable",
                    message="The current subscription price is unavailable",
                    kind=FailureKind.CONFLICT,
                )
            if current_price_id == prepared.new_price_id:
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
                new_price_id=prepared.new_price_id,
            )
        except BillingProviderUnavailable as exc:
            raise AppError(
                code="subscription_interval_failed",
                message="The subscription interval change could not be scheduled",
                kind=FailureKind.DEPENDENCY_FAILURE,
            ) from exc

        complete_operation = self._child(operation)
        self._executor.command(
            lambda capabilities: capabilities.billing.complete_interval_change(
                actor=actor,
                operation=complete_operation,
                schedule_id=schedule.schedule_id,
            )
        )
        effective_date = provider.current_period_end
        if effective_date is None:
            effective_date = datetime.fromtimestamp(
                schedule.current_phase_end,
                tz=timezone.utc,
            )
        old_interval = self._executor.query(
            lambda capabilities: capabilities.billing.interval_for_price(
                current_price_id
            )
        )
        self._record(
            BillingEvent(
                name="subscription_interval_scheduled",
                actor_id=actor.id,
                properties={
                    "subscription_id": subscription.stripe_subscription_id,
                    "schedule_id": schedule.schedule_id,
                    "old_interval": (
                        old_interval.value if old_interval is not None else "unknown"
                    ),
                    "new_interval": new_interval.value,
                    "effective_date": effective_date.isoformat(),
                },
            )
        )
        self._notify(
            IntervalChangeScheduledNotification(
                email=actor.email,
                display_name=actor.display_name,
                new_interval=new_interval.value,
            )
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

    def cancel_interval_change(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> IntervalChangeResponse:
        prepared = self._executor.query(
            lambda capabilities: capabilities.billing.prepare_cancel_interval_change(
                actor
            )
        )
        if isinstance(prepared, IntervalChangeResponse):
            return prepared
        schedule_id = prepared.stripe_schedule_id
        assert schedule_id
        try:
            self._payments.release_schedule(schedule_id)
        except BillingProviderUnavailable as exc:
            raise AppError(
                code="subscription_schedule_cancel_failed",
                message="The scheduled subscription change could not be canceled",
                kind=FailureKind.DEPENDENCY_FAILURE,
            ) from exc
        complete_operation = self._child(operation)
        changed = self._executor.command(
            lambda capabilities: capabilities.billing.complete_cancel_interval_change(
                actor=actor,
                operation=complete_operation,
                expected_schedule_id=schedule_id,
            )
        )
        if changed:
            self._record(
                BillingEvent(
                    name="subscription_interval_schedule_canceled",
                    actor_id=actor.id,
                    properties={
                        "subscription_id": prepared.stripe_subscription_id or "",
                        "schedule_id": schedule_id,
                    },
                )
            )
        return IntervalChangeResponse(
            success=True,
            message="Scheduled billing change has been canceled",
        )

    def _child(self, operation: OperationContext) -> OperationContext:
        return self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )

    def _record(self, event: BillingEvent) -> None:
        try:
            self._events.record(event)
        except Exception:
            logger.warning("billing.product_analytics.delivery_failed", exc_info=True)

    def _notify(self, notification: BillingNotification) -> None:
        try:
            self._notifier.send(notification)
        except Exception:
            logger.warning("billing.notification.delivery_failed", exc_info=True)

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
    def _provider_error(code: str, exc: Exception) -> NoReturn:
        messages = {
            "stripe_checkout_failed": "The checkout session could not be created",
            "stripe_portal_failed": "The billing portal could not be opened",
        }
        raise AppError(
            code=code,
            message=messages[code],
            kind=FailureKind.DEPENDENCY_FAILURE,
        ) from exc


__all__ = ["BillingWorkflow"]
