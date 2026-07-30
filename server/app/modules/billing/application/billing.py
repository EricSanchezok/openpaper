"""Session-bound billing queries and command stages.

Stripe, email, and telemetry calls deliberately live in the outer billing
workflows.  This capability only reads or mutates local business state and
appends attribution in the executor-owned UnitOfWork.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.modules.billing.application.contracts import (
    CheckoutSessionStatusResponse,
    IntervalChangeResponse,
    ScheduledIntervalChange,
    SubscriptionActionResponse,
    SubscriptionInterval,
    SubscriptionResponse,
    SubscriptionSummary,
    UsageResponse,
)
from app.modules.billing.application.ports import (
    ProviderCheckoutSession,
    ProviderSubscription,
    SubscriptionRecord,
    SubscriptionStore,
    UsageReader,
)
from app.modules.billing.application.webhook_contracts import (
    BillingWebhookChange,
    BillingWebhookResult,
    SubscriptionCreated,
    SubscriptionDeleted,
    SubscriptionScheduleCleared,
    SubscriptionStatusChanged,
    SubscriptionUpdated,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import SubscriptionPlan, SubscriptionStatus

BILLING_CUSTOMER_LINKED = OperationAction("billing.customer_linked")
BILLING_CHECKOUT_CREATED = OperationAction("billing.checkout_created")
BILLING_SUBSCRIPTION_REACTIVATED = OperationAction("billing.subscription_reactivated")
BILLING_CANCELLATION_REVERSED = OperationAction("billing.cancellation_reversed")
BILLING_INTERVAL_CHANGE_SCHEDULED = OperationAction("billing.interval_change_scheduled")
BILLING_INTERVAL_CHANGE_CANCELED = OperationAction("billing.interval_change_canceled")
BILLING_SUBSCRIPTION_SYNCED = OperationAction("billing.subscription_synced")
BILLING_SUBSCRIPTION_CREATED = OperationAction("billing.subscription_created")
BILLING_SUBSCRIPTION_UPDATED = OperationAction("billing.subscription_updated")
BILLING_SUBSCRIPTION_CANCELED = OperationAction("billing.subscription_canceled")
BILLING_PAYMENT_FAILED = OperationAction("billing.payment_failed")
BILLING_PAYMENT_SUCCEEDED = OperationAction("billing.payment_succeeded")
BILLING_SUBSCRIPTION_PAST_DUE = OperationAction("billing.subscription_past_due")
BILLING_INTERVAL_SCHEDULE_CLEARED = OperationAction("billing.interval_schedule_cleared")
_BILLING_STATUS_ACTIONS = {
    "payment_failed": BILLING_PAYMENT_FAILED,
    "payment_succeeded": BILLING_PAYMENT_SUCCEEDED,
    "subscription_past_due": BILLING_SUBSCRIPTION_PAST_DUE,
}


@dataclass(frozen=True, slots=True)
class CheckoutPreparation:
    subscription: SubscriptionRecord | None
    price_id: str


@dataclass(frozen=True, slots=True)
class ResumePreparation:
    subscription: SubscriptionRecord


@dataclass(frozen=True, slots=True)
class IntervalChangePreparation:
    subscription: SubscriptionRecord
    new_price_id: str


class Billing:
    """Local billing state owned by one executor operation."""

    def __init__(
        self,
        *,
        subscriptions: SubscriptionStore,
        usage: UsageReader,
        journal: OperationJournal,
        monthly_price_id: str | None,
        yearly_price_id: str | None,
    ) -> None:
        self._subscriptions = subscriptions
        self._usage = usage
        self._journal = journal
        self._price_ids = {
            SubscriptionInterval.MONTHLY: monthly_price_id,
            SubscriptionInterval.YEARLY: yearly_price_id,
        }

    def prepare_checkout(
        self,
        actor: Actor,
        interval: SubscriptionInterval,
    ) -> CheckoutPreparation:
        subscription = self._subscriptions.get(actor.id)
        if subscription and subscription.status in {
            "active",
            "past_due",
            "trialing",
        }:
            raise AppError(
                code="subscription_already_active",
                message="Use the customer portal to manage the active subscription",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return CheckoutPreparation(
            subscription=subscription,
            price_id=self._required_price(interval),
        )

    def complete_checkout(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        customer_id: str,
    ) -> None:
        resolution = self._subscriptions.save(
            actor.id,
            stripe_customer_id=customer_id,
        )
        resource = self._resource(resolution.record)
        if resolution.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=BILLING_CUSTOMER_LINKED,
                resources=(resource,),
            )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=BILLING_CHECKOUT_CREATED,
            resources=(resource,),
        )

    def prepare_portal(self, actor: Actor) -> str:
        subscription = self._subscriptions.get(actor.id)
        if not subscription or not subscription.stripe_customer_id:
            raise AppError(
                code="stripe_customer_not_found",
                message="No billing account is available for this user",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return subscription.stripe_customer_id

    def prepare_resume(
        self,
        actor: Actor,
    ) -> ResumePreparation | SubscriptionActionResponse:
        subscription = self._subscriptions.get(actor.id)
        if subscription is None:
            return SubscriptionActionResponse(
                success=False,
                error=(
                    "No existing subscription found. Create a new subscription instead."
                ),
            )
        if not subscription.stripe_customer_id:
            return SubscriptionActionResponse(
                success=False,
                error="No billing customer exists. Use checkout instead.",
            )
        if not subscription.stripe_subscription_id:
            return SubscriptionActionResponse(
                success=False,
                error="No billing subscription exists. Use checkout instead.",
            )
        return ResumePreparation(subscription=subscription)

    def complete_new_subscription(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider_subscription: ProviderSubscription,
    ) -> bool:
        resolution = self._subscriptions.save(
            actor.id,
            plan=SubscriptionPlan.RESEARCHER,
            stripe_subscription_id=provider_subscription.subscription_id,
            stripe_price_id=provider_subscription.price_id,
            status=provider_subscription.status,
            current_period_start=provider_subscription.current_period_start,
            current_period_end=provider_subscription.current_period_end,
            cancel_at_period_end=provider_subscription.cancel_at_period_end,
        )
        if not resolution.changed:
            return False
        self._journal.append(
            actor=actor,
            operation=operation,
            action=BILLING_SUBSCRIPTION_REACTIVATED,
            resources=(self._resource(resolution.record),),
        )
        return True

    def complete_cancellation_reversal(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> None:
        subscription = self._subscriptions.get(actor.id)
        if subscription is None:
            raise AppError(
                code="subscription_not_found",
                message="The billing subscription no longer exists",
                kind=FailureKind.CONFLICT,
            )
        resolution = self._subscriptions.save(
            actor.id,
            cancel_at_period_end=False,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=BILLING_CANCELLATION_REVERSED,
            resources=(self._resource(resolution.record),),
        )

    def prepare_interval_change(
        self,
        actor: Actor,
        new_interval: SubscriptionInterval,
    ) -> IntervalChangePreparation | IntervalChangeResponse:
        subscription = self._subscriptions.get(actor.id)
        if subscription is None:
            return IntervalChangeResponse(
                success=False,
                error="No existing subscription found",
            )
        if not subscription.stripe_subscription_id:
            return IntervalChangeResponse(
                success=False,
                error="No billing subscription ID found",
            )
        return IntervalChangePreparation(
            subscription=subscription,
            new_price_id=self._required_price(new_interval),
        )

    def complete_interval_change(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        schedule_id: str,
    ) -> bool:
        resolution = self._subscriptions.save(
            actor.id,
            stripe_schedule_id=schedule_id,
        )
        if not resolution.changed:
            return False
        self._journal.append(
            actor=actor,
            operation=operation,
            action=BILLING_INTERVAL_CHANGE_SCHEDULED,
            resources=(self._resource(resolution.record),),
        )
        return True

    def prepare_cancel_interval_change(
        self,
        actor: Actor,
    ) -> SubscriptionRecord | IntervalChangeResponse:
        subscription = self._subscriptions.get(actor.id)
        if subscription is None:
            return IntervalChangeResponse(
                success=False,
                error="No existing subscription found",
            )
        if not subscription.stripe_schedule_id:
            return IntervalChangeResponse(
                success=False,
                error="No scheduled change found",
            )
        return subscription

    def complete_cancel_interval_change(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        expected_schedule_id: str,
    ) -> bool:
        subscription = self._subscriptions.get(actor.id)
        if (
            subscription is None
            or subscription.stripe_schedule_id != expected_schedule_id
        ):
            return False
        resolution = self._subscriptions.save(
            actor.id,
            stripe_schedule_id=None,
        )
        if not resolution.changed:
            return False
        self._journal.append(
            actor=actor,
            operation=operation,
            action=BILLING_INTERVAL_CHANGE_CANCELED,
            resources=(self._resource(resolution.record),),
        )
        return True

    def get_subscription(self, actor: Actor) -> SubscriptionResponse:
        return self._subscription_response(self._subscriptions.get(actor.id))

    def prepare_subscription_refresh(
        self,
        actor: Actor,
    ) -> SubscriptionRecord | None:
        return self._subscriptions.get(actor.id)

    def complete_subscription_refresh(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider_subscription: ProviderSubscription,
    ) -> None:
        existing = self._subscriptions.get(actor.id)
        if (
            existing is None
            or existing.stripe_subscription_id != provider_subscription.subscription_id
        ):
            return
        resolution = self._subscriptions.save(
            actor.id,
            status=provider_subscription.status,
            stripe_price_id=provider_subscription.price_id,
            current_period_start=provider_subscription.current_period_start,
            current_period_end=provider_subscription.current_period_end,
            cancel_at_period_end=provider_subscription.cancel_at_period_end,
        )
        if resolution.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=BILLING_SUBSCRIPTION_SYNCED,
                resources=(self._resource(resolution.record),),
            )

    def checkout_status(
        self,
        checkout: ProviderCheckoutSession,
    ) -> CheckoutSessionStatusResponse:
        backend_found = False
        backend_status = None
        if checkout.status == "complete" and checkout.client_reference_id:
            try:
                user_id = int(checkout.client_reference_id)
            except ValueError:
                pass
            else:
                subscription = self._subscriptions.get(user_id)
                if subscription and subscription.stripe_subscription_id:
                    backend_found = True
                    backend_status = subscription.status or "unknown"
        return CheckoutSessionStatusResponse(
            status=checkout.status,
            customer_email=checkout.customer_email,
            backend_subscription_found=backend_found,
            backend_subscription_status=backend_status,
        )

    def get_usage(self, actor: Actor) -> UsageResponse:
        return self._usage.read(actor)

    def webhook_owner_id(
        self,
        *,
        user_id: int | None = None,
        customer_id: str | None = None,
        subscription_id: str | None = None,
    ) -> int | None:
        candidates: set[int] = set()
        if user_id is not None:
            candidates.add(user_id)
        if customer_id is not None:
            subscription = self._subscriptions.get_by_customer_id(customer_id)
            if subscription is not None:
                candidates.add(subscription.user_id)
        if subscription_id is not None:
            subscription = self._subscriptions.get_by_subscription_id(subscription_id)
            if subscription is not None:
                candidates.add(subscription.user_id)
        if len(candidates) > 1:
            raise AppError(
                code="stripe_webhook_owner_conflict",
                message="The Stripe event does not resolve to one billing owner",
                kind=FailureKind.CONFLICT,
            )
        return next(iter(candidates), None)

    def apply_webhook(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        change: BillingWebhookChange,
    ) -> BillingWebhookResult:
        if isinstance(change, SubscriptionCreated):
            existing = self._subscriptions.get_by_customer_id(change.customer_id)
            self._require_owner(actor, existing)
            resolution = self._subscriptions.save(
                actor.id,
                plan=SubscriptionPlan.RESEARCHER,
                stripe_customer_id=change.customer_id,
                stripe_subscription_id=change.subscription_id,
                stripe_price_id=change.price_id,
                status=change.status,
                current_period_start=change.current_period_start,
                current_period_end=change.current_period_end,
                cancel_at_period_end=change.cancel_at_period_end,
            )
            action = BILLING_SUBSCRIPTION_CREATED
            newly_canceled = False
        elif isinstance(change, SubscriptionUpdated):
            existing = self._subscriptions.get_by_subscription_id(
                change.subscription_id
            )
            self._require_owner(actor, existing)
            assert existing is not None
            newly_canceled = (
                change.cancel_at_period_end and not existing.cancel_at_period_end
            )
            resolution = self._subscriptions.save(
                actor.id,
                stripe_price_id=change.price_id,
                status=change.status,
                current_period_start=change.current_period_start,
                current_period_end=change.current_period_end,
                cancel_at_period_end=change.cancel_at_period_end,
            )
            action = BILLING_SUBSCRIPTION_UPDATED
        elif isinstance(change, SubscriptionDeleted):
            existing = self._subscriptions.get_by_subscription_id(
                change.subscription_id
            )
            self._require_owner(actor, existing)
            resolution = self._subscriptions.save(
                actor.id,
                plan=SubscriptionPlan.BASIC,
                stripe_price_id=change.price_id,
                status=SubscriptionStatus.CANCELED,
                cancel_at_period_end=True,
            )
            action = BILLING_SUBSCRIPTION_CANCELED
            newly_canceled = False
        elif isinstance(change, SubscriptionStatusChanged):
            existing = self._subscriptions.get_by_subscription_id(
                change.subscription_id
            )
            self._require_owner(actor, existing)
            resolution = self._subscriptions.save(
                actor.id,
                status=change.status,
            )
            action = _BILLING_STATUS_ACTIONS[change.action]
            newly_canceled = False
        elif isinstance(change, SubscriptionScheduleCleared):
            existing = self._subscriptions.get_by_subscription_id(
                change.subscription_id
            )
            self._require_owner(actor, existing)
            assert existing is not None
            if existing.stripe_schedule_id != change.schedule_id:
                return BillingWebhookResult(changed=False)
            resolution = self._subscriptions.save(
                actor.id,
                stripe_schedule_id=None,
            )
            action = BILLING_INTERVAL_SCHEDULE_CLEARED
            newly_canceled = False
        else:
            raise TypeError(f"Unsupported billing webhook change: {type(change)!r}")

        if resolution.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=action,
                resources=(self._resource(resolution.record),),
            )
        return BillingWebhookResult(
            changed=resolution.changed,
            cancellation_newly_scheduled=newly_canceled,
        )

    def _subscription_response(
        self,
        subscription: SubscriptionRecord | None,
    ) -> SubscriptionResponse:
        if subscription is None:
            return SubscriptionResponse(has_subscription=False)
        interval = self.interval_for_price(subscription.stripe_price_id)
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

    def _required_price(self, interval: SubscriptionInterval) -> str:
        price_id = self._price_ids[interval]
        if not price_id:
            raise AppError(
                code="stripe_price_not_configured",
                message="Subscription billing is not configured",
                kind=FailureKind.UNAVAILABLE,
            )
        return price_id

    def interval_for_price(
        self,
        price_id: str | None,
    ) -> SubscriptionInterval | None:
        if price_id and price_id == self._price_ids[SubscriptionInterval.MONTHLY]:
            return SubscriptionInterval.MONTHLY
        if price_id and price_id == self._price_ids[SubscriptionInterval.YEARLY]:
            return SubscriptionInterval.YEARLY
        return None

    @staticmethod
    def _require_owner(
        actor: Actor,
        subscription: SubscriptionRecord | None,
    ) -> None:
        if subscription is None:
            raise AppError(
                code="stripe_subscription_not_found",
                message="The Stripe subscription is not linked to a Scholens account",
                kind=FailureKind.NOT_FOUND,
            )
        if subscription.user_id != actor.id:
            raise AppError(
                code="stripe_webhook_owner_conflict",
                message="The Stripe event owner does not match the resolved actor",
                kind=FailureKind.CONFLICT,
            )

    @staticmethod
    def _resource(subscription: SubscriptionRecord) -> ResourceRef:
        return ResourceRef("subscription", str(subscription.id))


__all__ = [
    "Billing",
    "CheckoutPreparation",
    "IntervalChangePreparation",
    "ResumePreparation",
]
