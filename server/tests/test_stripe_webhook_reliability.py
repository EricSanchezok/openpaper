from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.bootstrap.adapters.stripe_webhook import (
    StripeWebhookWorkflow,
    stripe_event_reference,
)
from app.modules.billing.application.webhook_contracts import BillingWebhookResult
from app.modules.billing.infrastructure.stripe_webhook_ledger import WebhookClaim
from app.shared.application import (
    Actor,
    CredentialKind,
    OperationContextFactory,
    RequestReference,
    WebhookOrigin,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import StripeWebhookEventStatus


class _Executor:
    def __init__(self, capabilities: object) -> None:
        self.capabilities = capabilities
        self.active = False

    def query(self, operation: object) -> object:
        self.active = True
        try:
            return operation(self.capabilities)  # type: ignore[operator]
        finally:
            self.active = False

    def command(self, operation: object) -> object:
        self.active = True
        try:
            return operation(self.capabilities)  # type: ignore[operator]
        finally:
            self.active = False

    async def command_async(self, operation: object) -> object:
        self.active = True
        try:
            return await operation(self.capabilities)  # type: ignore[operator]
        finally:
            self.active = False


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        display_name="Reader Example",
        status="active",
        email_verified=True,
    )


def _workflow(
    *,
    billing: MagicMock | None = None,
    identity: MagicMock | None = None,
    events: MagicMock | None = None,
    notifier: MagicMock | None = None,
) -> tuple[StripeWebhookWorkflow, _Executor]:
    billing = billing or MagicMock()
    billing.webhook_owner_id.return_value = 7
    billing.apply_webhook.return_value = BillingWebhookResult(changed=True)
    identity = identity or MagicMock()
    identity.resolve_actor_by_user_id.return_value = _actor()
    capabilities = SimpleNamespace(billing=billing, identity=identity)
    executor = _Executor(capabilities)
    workflow = StripeWebhookWorkflow(
        executor=executor,  # type: ignore[arg-type]
        session_factory=MagicMock(),
        engine=MagicMock(),
        operation_factory=OperationContextFactory(),
        events=events or MagicMock(),
        notifier=notifier or MagicMock(),
        webhook_secret="whsec_test",
    )
    return workflow, executor


def _lock() -> MagicMock:
    lock = MagicMock()
    lock.acquire.return_value = True
    return lock


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_before_ledger_or_context() -> None:
    workflow, _ = _workflow()
    workflow._claim = MagicMock()  # type: ignore[method-assign]
    with patch(
        "app.bootstrap.adapters.stripe_webhook.construct_stripe_event",
        side_effect=ValueError("bad signature"),
    ):
        with pytest.raises(AppError) as exc_info:
            await workflow.process(
                payload=b"{}",
                signature="invalid",
                request_reference=RequestReference(uuid4()),
            )

    assert exc_info.value.kind is FailureKind.INVALID_ARGUMENT
    workflow._claim.assert_not_called()


@pytest.mark.asyncio
async def test_completed_delivery_is_acknowledged_without_reprocessing() -> None:
    workflow, _ = _workflow()
    workflow._claim = MagicMock(  # type: ignore[method-assign]
        return_value=WebhookClaim(
            should_process=False,
            status=StripeWebhookEventStatus.COMPLETED,
        )
    )
    workflow._complete = MagicMock()  # type: ignore[method-assign]
    lock = _lock()
    with (
        patch(
            "app.bootstrap.adapters.stripe_webhook.construct_stripe_event",
            return_value={"id": "evt_done", "type": "invoice.payment_succeeded"},
        ),
        patch(
            "app.bootstrap.adapters.stripe_webhook.AdvisoryLock",
            return_value=lock,
        ),
    ):
        result = await workflow.process(
            payload=b"{}",
            signature="valid",
            request_reference=RequestReference(uuid4()),
        )

    assert result == {"success": True, "duplicate": True}
    workflow._complete.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.asyncio
async def test_unsupported_event_is_marked_ignored_without_actor_resolution() -> None:
    billing = MagicMock()
    workflow, _ = _workflow(billing=billing)
    workflow._claim = MagicMock(  # type: ignore[method-assign]
        return_value=WebhookClaim(
            should_process=True,
            status=StripeWebhookEventStatus.PROCESSING,
        )
    )
    workflow._complete = MagicMock()  # type: ignore[method-assign]
    with (
        patch(
            "app.bootstrap.adapters.stripe_webhook.construct_stripe_event",
            return_value={"id": "evt_ignored", "type": "customer.created"},
        ),
        patch(
            "app.bootstrap.adapters.stripe_webhook.AdvisoryLock",
            return_value=_lock(),
        ),
    ):
        result = await workflow.process(
            payload=b"{}",
            signature="valid",
            request_reference=RequestReference(uuid4()),
        )

    assert result == {"success": True, "ignored": True}
    workflow._complete.assert_called_once_with(
        event_id="evt_ignored",
        status=StripeWebhookEventStatus.IGNORED,
    )
    billing.webhook_owner_id.assert_not_called()


@pytest.mark.asyncio
async def test_business_failure_marks_technical_ledger_failed() -> None:
    billing = MagicMock()
    billing.webhook_owner_id.return_value = 7
    billing.apply_webhook.side_effect = RuntimeError("database unavailable")
    workflow, _ = _workflow(billing=billing)
    workflow._claim = MagicMock(  # type: ignore[method-assign]
        return_value=WebhookClaim(
            should_process=True,
            status=StripeWebhookEventStatus.PROCESSING,
        )
    )
    workflow._fail = MagicMock()  # type: ignore[method-assign]
    event = {
        "id": "evt_failed",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_1",
                "customer": "cus_1",
                "items": {
                    "data": [
                        {
                            "price": {"id": "price_test_monthly"},
                        }
                    ]
                },
            }
        },
    }
    with (
        patch(
            "app.bootstrap.adapters.stripe_webhook.construct_stripe_event",
            return_value=event,
        ),
        patch(
            "app.bootstrap.adapters.stripe_webhook.AdvisoryLock",
            return_value=_lock(),
        ),
    ):
        with pytest.raises(AppError) as exc_info:
            await workflow.process(
                payload=b"{}",
                signature="valid",
                request_reference=RequestReference(uuid4()),
            )

    assert exc_info.value.kind is FailureKind.INTERNAL
    workflow._fail.assert_called_once_with(
        event_id="evt_failed",
        error_code="stripe_webhook_failed",
    )


@pytest.mark.asyncio
async def test_verified_event_uses_safe_provenance_and_post_commit_effects() -> None:
    billing = MagicMock()
    billing.webhook_owner_id.return_value = 7
    billing.apply_webhook.return_value = BillingWebhookResult(changed=True)
    events = MagicMock()
    notifier = MagicMock()
    workflow, executor = _workflow(
        billing=billing,
        events=events,
        notifier=notifier,
    )
    events.record.side_effect = lambda _event: assert_not_active(executor)
    notifier.send.side_effect = lambda _notification: assert_not_active(executor)
    workflow._claim = MagicMock(  # type: ignore[method-assign]
        return_value=WebhookClaim(
            should_process=True,
            status=StripeWebhookEventStatus.PROCESSING,
        )
    )
    workflow._complete = MagicMock()  # type: ignore[method-assign]
    request_reference = RequestReference(uuid4())
    stripe_object = SimpleNamespace(
        id="sub_1",
        customer="cus_1",
        status="active",
        cancel_at_period_end=False,
        items={
            "data": [
                {
                    "price": SimpleNamespace(id="price_test_monthly"),
                    "current_period_start": 1_800_000_000,
                    "current_period_end": 1_900_000_000,
                }
            ]
        },
    )
    event = {
        "id": "evt_created",
        "type": "customer.subscription.created",
        "data": {"object": stripe_object},
    }
    with (
        patch(
            "app.bootstrap.adapters.stripe_webhook.construct_stripe_event",
            return_value=event,
        ),
        patch(
            "app.bootstrap.adapters.stripe_webhook.AdvisoryLock",
            return_value=_lock(),
        ),
    ):
        assert await workflow.process(
            payload=b"{}",
            signature="valid",
            request_reference=request_reference,
        ) == {"success": True}

    operation = billing.apply_webhook.call_args.kwargs["operation"]
    assert isinstance(operation.origin, WebhookOrigin)
    assert operation.origin.request == request_reference
    assert operation.origin.provider_event_ref == stripe_event_reference("evt_created")
    assert operation.credential is not None
    assert operation.credential.kind is CredentialKind.PROVIDER_SIGNATURE
    workflow._complete.assert_called_once_with(event_id="evt_created")
    events.record.assert_called_once()
    notifier.send.assert_called_once()


def assert_not_active(executor: _Executor) -> None:
    assert executor.active is False
