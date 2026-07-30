"""Verified Stripe webhook workflow with short, explicit transactions."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.helpers.advisory_locks import AdvisoryLock, AdvisoryLockNamespace
from app.modules.billing.application.ports import (
    BillingEvent,
    BillingEvents,
    BillingIssueNotification,
    BillingNotification,
    BillingNotifier,
    CancellationConfirmedNotification,
    SubscriptionWelcomeNotification,
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
from app.modules.billing.infrastructure.config import is_valid_price_id
from app.modules.billing.infrastructure.stripe_client import construct_stripe_event
from app.modules.billing.infrastructure.stripe_webhook_ledger import (
    WebhookClaim,
    begin_webhook_attempt,
    complete_webhook,
    fail_webhook,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    WebhookOrigin,
)
from app.shared.application.canonical_digest import canonical_sha256
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import StripeWebhookEventStatus
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from app.bootstrap.capabilities import ApplicationCapabilities

logger = logging.getLogger(__name__)

PROVIDER_EVENT_REFERENCE_DOMAIN = "scholens.provider.event_ref.v1"
SUPPORTED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.updated",
        "customer.subscription.created",
        "customer.subscription.deleted",
        "invoice.payment_failed",
        "invoice.payment_action_required",
        "customer.subscription.past_due",
        "invoice.payment_succeeded",
        "subscription_schedule.completed",
        "subscription_schedule.released",
    }
)


def stripe_event_reference(event_id: str) -> str:
    return canonical_sha256(
        PROVIDER_EVENT_REFERENCE_DOMAIN,
        "stripe",
        event_id,
    )


@dataclass(frozen=True, slots=True)
class _OwnerReference:
    user_id: int | None = None
    customer_id: str | None = None
    subscription_id: str | None = None


class StripeWebhookWorkflow:
    """Authenticate first, then apply one business change and journal atomically."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        session_factory: sessionmaker[Session],
        engine: Engine,
        operation_factory: OperationContextFactory,
        events: BillingEvents,
        notifier: BillingNotifier,
        webhook_secret: str | None,
    ) -> None:
        self._executor = executor
        self._session_factory = session_factory
        self._engine = engine
        self._operation_factory = operation_factory
        self._events = events
        self._notifier = notifier
        self._webhook_secret = webhook_secret

    async def process(
        self,
        *,
        payload: bytes,
        signature: str,
        request_reference: RequestReference,
    ) -> dict[str, object]:
        event = self._verify(payload=payload, signature=signature)
        event_id = str(event["id"])
        event_type = str(event["type"])
        event_lock = AdvisoryLock(
            self._engine,
            namespace=AdvisoryLockNamespace.STRIPE_WEBHOOK,
            key=event_id,
        )
        if not event_lock.acquire():
            raise AppError(
                code="stripe_webhook_in_progress",
                message="Stripe webhook processing is already in progress",
                kind=FailureKind.CONFLICT,
            )

        ledger_started = False
        try:
            claim = self._claim(event_id=event_id, event_type=event_type)
            ledger_started = True
            if not claim.should_process:
                return {"success": True, "duplicate": True}
            if event_type not in SUPPORTED_EVENTS:
                self._complete(
                    event_id=event_id,
                    status=StripeWebhookEventStatus.IGNORED,
                )
                return {"success": True, "ignored": True}

            stripe_object = event["data"]["object"]
            change, owner_reference, ignored = self._interpret(
                event_type,
                stripe_object,
            )
            if ignored:
                self._complete(
                    event_id=event_id,
                    status=StripeWebhookEventStatus.IGNORED,
                )
                return {"success": True, "ignored": True}

            actor = self._resolve_actor(owner_reference)
            if actor is None:
                self._complete(event_id=event_id)
                return {"success": True, "no_op": True}

            operation = self._operation_factory.root(
                initiated_by=OperationInitiator.SYSTEM,
                origin=WebhookOrigin(
                    request=request_reference,
                    provider="stripe",
                    provider_event_ref=stripe_event_reference(event_id),
                ),
                credential=CredentialRef(
                    CredentialKind.PROVIDER_SIGNATURE,
                    credential_id="stripe",
                ),
            )
            result = BillingWebhookResult(changed=False)
            if change is not None:
                result = self._executor.command(
                    lambda capabilities: capabilities.billing.apply_webhook(
                        actor=actor,
                        operation=operation,
                        change=change,
                    )
                )

            self._complete(event_id=event_id)
            self._deliver_effects(
                event_type=event_type,
                stripe_object=stripe_object,
                actor=actor,
                result=result,
            )
            return {"success": True}
        except AppError:
            if ledger_started:
                self._fail(
                    event_id=event_id,
                    error_code="webhook_http_error",
                )
            raise
        except Exception as exc:
            if ledger_started:
                self._fail(
                    event_id=event_id,
                    error_code="stripe_webhook_failed",
                )
            logger.exception("Error processing Stripe webhook event %s", event_id)
            raise AppError(
                code="stripe_webhook_failed",
                message="Stripe webhook processing failed",
                kind=FailureKind.INTERNAL,
            ) from exc
        finally:
            event_lock.release()

    def _verify(self, *, payload: bytes, signature: str) -> Any:
        if not self._webhook_secret:
            raise AppError(
                code="stripe_webhook_not_configured",
                message="Stripe webhook is not configured",
                kind=FailureKind.INTERNAL,
            )
        try:
            return construct_stripe_event(
                payload,
                signature,
                self._webhook_secret,
            )
        except Exception as exc:
            logger.warning("Invalid Stripe webhook signature", exc_info=True)
            raise AppError(
                code="invalid_stripe_signature",
                message="Invalid Stripe webhook signature",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from exc

    def _claim(self, *, event_id: str, event_type: str) -> WebhookClaim:
        with self._session_factory() as session, session.begin():
            return begin_webhook_attempt(
                session,
                event_id=event_id,
                event_type=event_type,
            )

    def _complete(
        self,
        *,
        event_id: str,
        status: StripeWebhookEventStatus = StripeWebhookEventStatus.COMPLETED,
    ) -> None:
        with self._session_factory() as session, session.begin():
            complete_webhook(
                session,
                event_id=event_id,
                status=status,
            )

    def _fail(self, *, event_id: str, error_code: str) -> None:
        with self._session_factory() as session, session.begin():
            fail_webhook(
                session,
                event_id=event_id,
                error_code=error_code,
            )

    def _resolve_actor(self, owner: _OwnerReference) -> Actor | None:
        def resolve(capabilities: ApplicationCapabilities) -> Actor | None:
            owner_id = capabilities.billing.webhook_owner_id(
                user_id=owner.user_id,
                customer_id=owner.customer_id,
                subscription_id=owner.subscription_id,
            )
            if owner_id is None:
                return None
            actor = capabilities.identity.resolve_actor_by_user_id(owner_id)
            if actor.id != owner_id:
                raise RuntimeError("stripe_webhook_owner_mismatch")
            return actor

        return self._executor.query(resolve)

    def _interpret(
        self,
        event_type: str,
        stripe_object: Any,
    ) -> tuple[BillingWebhookChange | None, _OwnerReference, bool]:
        if event_type == "checkout.session.completed":
            user_id = _positive_int(_get(stripe_object, "client_reference_id"))
            return (
                None,
                _OwnerReference(
                    user_id=user_id,
                    customer_id=_text(_get(stripe_object, "customer")),
                ),
                False,
            )

        if event_type in {
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        }:
            subscription_id = _required_text(
                _get(stripe_object, "id"),
                "Stripe subscription ID",
            )
            customer_id = _text(_get(stripe_object, "customer"))
            price_id, period_start, period_end = _subscription_item(stripe_object)
            if price_id and not is_valid_price_id(price_id):
                return (
                    None,
                    _OwnerReference(
                        customer_id=customer_id,
                        subscription_id=subscription_id,
                    ),
                    True,
                )
            owner = _OwnerReference(
                customer_id=customer_id,
                subscription_id=subscription_id,
            )
            if event_type == "customer.subscription.created":
                if customer_id is None:
                    raise ValueError("Stripe subscription customer is missing")
                return (
                    SubscriptionCreated(
                        customer_id=customer_id,
                        subscription_id=subscription_id,
                        price_id=price_id,
                        status=_required_text(
                            _get(stripe_object, "status"),
                            "Stripe subscription status",
                        ),
                        current_period_start=period_start,
                        current_period_end=period_end,
                        cancel_at_period_end=bool(
                            _get(stripe_object, "cancel_at_period_end", False)
                        ),
                    ),
                    owner,
                    False,
                )
            if event_type == "customer.subscription.updated":
                cancel_at_period_end = (
                    bool(_get(stripe_object, "cancel_at_period_end", False))
                    or _get(stripe_object, "cancel_at") is not None
                )
                return (
                    SubscriptionUpdated(
                        subscription_id=subscription_id,
                        price_id=price_id,
                        status=_required_text(
                            _get(stripe_object, "status"),
                            "Stripe subscription status",
                        ),
                        current_period_start=period_start,
                        current_period_end=period_end,
                        cancel_at_period_end=cancel_at_period_end,
                    ),
                    owner,
                    False,
                )
            return (
                SubscriptionDeleted(
                    subscription_id=subscription_id,
                    price_id=price_id,
                ),
                owner,
                False,
            )

        if event_type in {
            "invoice.payment_failed",
            "invoice.payment_succeeded",
            "invoice.payment_action_required",
        }:
            invoice_subscription_id = _text(_get(stripe_object, "subscription"))
            owner = _OwnerReference(
                customer_id=_text(_get(stripe_object, "customer")),
                subscription_id=invoice_subscription_id,
            )
            if event_type == "invoice.payment_action_required":
                return None, owner, False
            if invoice_subscription_id is None:
                return None, owner, False
            failed = event_type == "invoice.payment_failed"
            return (
                SubscriptionStatusChanged(
                    subscription_id=invoice_subscription_id,
                    status="past_due" if failed else "active",
                    action="payment_failed" if failed else "payment_succeeded",
                ),
                owner,
                False,
            )

        if event_type == "customer.subscription.past_due":
            subscription_id = _required_text(
                _get(stripe_object, "id"),
                "Stripe subscription ID",
            )
            return (
                SubscriptionStatusChanged(
                    subscription_id=subscription_id,
                    status="past_due",
                    action="subscription_past_due",
                ),
                _OwnerReference(subscription_id=subscription_id),
                False,
            )

        schedule_id = _required_text(
            _get(stripe_object, "id"),
            "Stripe schedule ID",
        )
        schedule_subscription_id = _text(_get(stripe_object, "subscription"))
        if schedule_subscription_id is None:
            return None, _OwnerReference(), False
        return (
            SubscriptionScheduleCleared(
                subscription_id=schedule_subscription_id,
                schedule_id=schedule_id,
            ),
            _OwnerReference(subscription_id=schedule_subscription_id),
            False,
        )

    def _deliver_effects(
        self,
        *,
        event_type: str,
        stripe_object: Any,
        actor: Actor,
        result: BillingWebhookResult,
    ) -> None:
        properties = _telemetry_properties(event_type, stripe_object)
        if (
            event_type == "customer.subscription.updated"
            and not result.cancellation_newly_scheduled
        ):
            properties = None
        if properties is not None:
            self._record(
                BillingEvent(
                    name=properties[0],
                    actor_id=actor.id,
                    properties=properties[1],
                )
            )

        if event_type == "customer.subscription.created" and result.changed:
            self._notify(
                SubscriptionWelcomeNotification(
                    email=actor.email,
                    display_name=actor.display_name,
                )
            )
        elif (
            event_type == "customer.subscription.updated"
            and result.cancellation_newly_scheduled
        ):
            self._notify(
                CancellationConfirmedNotification(
                    email=actor.email,
                    display_name=actor.display_name,
                )
            )
        elif event_type in {
            "invoice.payment_failed",
            "invoice.payment_action_required",
            "customer.subscription.past_due",
        }:
            messages = {
                "invoice.payment_failed": (
                    "Payment failed for your subscription. "
                    "Please update your payment method"
                ),
                "invoice.payment_action_required": (
                    "Payment action required for your subscription. "
                    "Please complete the required action."
                ),
                "customer.subscription.past_due": (
                    "Your subscription is past due. Please update your payment "
                    "method to avoid service interruption."
                ),
            }
            self._notify(
                BillingIssueNotification(
                    email=actor.email,
                    display_name=actor.display_name,
                    issue=messages[event_type],
                )
            )

    def _record(self, event: BillingEvent) -> None:
        try:
            self._events.record(event)
        except Exception:
            logger.warning("Stripe webhook telemetry delivery failed", exc_info=True)

    def _notify(self, notification: BillingNotification) -> None:
        try:
            self._notifier.send(notification)
        except Exception:
            logger.warning("Stripe webhook notification delivery failed", exc_info=True)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(value: Any, label: str) -> str:
    text = _text(value)
    if text is None:
        raise ValueError(f"{label} is missing")
    return text


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _subscription_item(
    subscription: Any,
) -> tuple[str | None, datetime | None, datetime | None]:
    items = _get(subscription, "items")
    data = _get(items, "data", ()) or ()
    item = data[0] if data else None
    price = _get(item, "price") if item is not None else None
    return (
        _text(_get(price, "id")),
        _timestamp(_get(item, "current_period_start")),
        _timestamp(_get(item, "current_period_end")),
    )


def _telemetry_properties(
    event_type: str,
    stripe_object: Any,
) -> tuple[str, dict[str, object]] | None:
    subscription_id = _text(_get(stripe_object, "subscription"))
    customer_id = _text(_get(stripe_object, "customer"))
    object_id = _text(_get(stripe_object, "id"))
    if event_type == "checkout.session.completed":
        return (
            "checkout_completed",
            {
                "subscription_id": subscription_id,
                "customer_id": customer_id,
            },
        )
    if event_type == "customer.subscription.created":
        return (
            "subscription_created",
            {
                "subscription_id": object_id,
                "customer_id": customer_id,
                "status": _text(_get(stripe_object, "status")),
            },
        )
    if event_type in {
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        return (
            "subscription_canceled",
            {
                "subscription_id": object_id,
                "customer_id": customer_id,
                "cancel_at_period_end": bool(
                    _get(stripe_object, "cancel_at_period_end", False)
                ),
            },
        )
    names = {
        "invoice.payment_failed": "payment_failed",
        "invoice.payment_succeeded": "payment_succeeded",
        "invoice.payment_action_required": "payment_action_required",
        "customer.subscription.past_due": "subscription_past_due",
    }
    name = names.get(event_type)
    if name is None:
        return None
    return (
        name,
        {
            "subscription_id": subscription_id or object_id,
            "invoice_id": (object_id if event_type.startswith("invoice.") else None),
        },
    )


__all__ = [
    "PROVIDER_EVENT_REFERENCE_DOMAIN",
    "StripeWebhookWorkflow",
    "stripe_event_reference",
]
