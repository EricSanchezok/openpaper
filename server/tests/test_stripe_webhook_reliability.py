from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.modules.billing.infrastructure import stripe_webhook as webhook
from app.modules.billing.infrastructure.stripe_webhook_ledger import WebhookClaim
from app.database.models import StripeWebhookEventStatus
from app.shared.domain import AppError
from sqlalchemy.orm import Session


def _lock(*, acquired: bool = True) -> MagicMock:
    lock = MagicMock()
    lock.acquire.return_value = acquired
    return lock


@pytest.mark.asyncio
async def test_invalid_signature_is_rejected_without_creating_ledger_row() -> None:
    db = MagicMock(spec=Session)
    with (
        patch.object(webhook, "construct_stripe_event", side_effect=ValueError("bad")),
        patch.object(webhook, "begin_webhook_attempt") as begin,
    ):
        with pytest.raises(AppError) as exc_info:
            await webhook.process_stripe_webhook(
                payload=b"{}",
                stripe_signature="invalid",
                db=db,
            )

    assert exc_info.value.status_code == 400
    begin.assert_not_called()


@pytest.mark.asyncio
async def test_completed_delivery_is_acknowledged_without_reprocessing() -> None:
    db = MagicMock(spec=Session)
    lock = _lock()
    with (
        patch.object(
            webhook,
            "construct_stripe_event",
            return_value={"id": "evt_done", "type": "invoice.payment_succeeded"},
        ),
        patch.object(webhook, "AdvisoryLock", return_value=lock),
        patch.object(
            webhook,
            "begin_webhook_attempt",
            return_value=WebhookClaim(
                should_process=False,
                status=StripeWebhookEventStatus.COMPLETED,
            ),
        ),
        patch.object(webhook, "complete_webhook") as complete,
    ):
        result = await webhook.process_stripe_webhook(
            payload=b"{}",
            stripe_signature="valid",
            db=db,
        )

    assert result == {"success": True, "duplicate": True}
    complete.assert_not_called()
    lock.release.assert_called_once()


@pytest.mark.asyncio
async def test_unsupported_event_is_recorded_as_ignored() -> None:
    db = MagicMock(spec=Session)
    lock = _lock()
    with (
        patch.object(
            webhook,
            "construct_stripe_event",
            return_value={"id": "evt_ignored", "type": "customer.created"},
        ),
        patch.object(webhook, "AdvisoryLock", return_value=lock),
        patch.object(
            webhook,
            "begin_webhook_attempt",
            return_value=WebhookClaim(
                should_process=True,
                status=StripeWebhookEventStatus.PROCESSING,
            ),
        ),
        patch.object(webhook, "complete_webhook") as complete,
    ):
        result = await webhook.process_stripe_webhook(
            payload=b"{}",
            stripe_signature="valid",
            db=db,
        )

    assert result == {"success": True, "ignored": True}
    complete.assert_called_once_with(
        db,
        event_id="evt_ignored",
        status=StripeWebhookEventStatus.IGNORED,
    )


@pytest.mark.asyncio
async def test_concurrent_delivery_returns_retryable_error_without_failing_owner() -> (
    None
):
    db = MagicMock(spec=Session)
    lock = _lock(acquired=False)
    with (
        patch.object(
            webhook,
            "construct_stripe_event",
            return_value={"id": "evt_busy", "type": "invoice.payment_succeeded"},
        ),
        patch.object(webhook, "AdvisoryLock", return_value=lock),
        patch.object(webhook, "fail_webhook") as fail,
    ):
        with pytest.raises(AppError) as exc_info:
            await webhook.process_stripe_webhook(
                payload=b"{}",
                stripe_signature="valid",
                db=db,
            )

    assert exc_info.value.status_code == 409
    fail.assert_not_called()


@pytest.mark.asyncio
async def test_core_processing_failure_is_recorded_and_retried_by_stripe() -> None:
    db = MagicMock(spec=Session)
    lock = _lock()
    stripe_object = SimpleNamespace(id="sub_1")
    with (
        patch.object(
            webhook,
            "construct_stripe_event",
            return_value={
                "id": "evt_failed",
                "type": "customer.subscription.deleted",
                "data": {"object": stripe_object},
            },
        ),
        patch.object(webhook, "AdvisoryLock", return_value=lock),
        patch.object(
            webhook,
            "begin_webhook_attempt",
            return_value=WebhookClaim(
                should_process=True,
                status=StripeWebhookEventStatus.PROCESSING,
            ),
        ),
        patch.object(
            webhook.subscription_repository,
            "get_by_stripe_subscription_id",
            side_effect=RuntimeError("database unavailable"),
        ),
        patch.object(webhook, "fail_webhook") as fail,
    ):
        with pytest.raises(AppError) as exc_info:
            await webhook.process_stripe_webhook(
                payload=b"{}",
                stripe_signature="valid",
                db=db,
            )

    assert exc_info.value.status_code == 500
    fail.assert_called_once_with(
        db,
        event_id="evt_failed",
        error_code="stripe_webhook_failed",
    )
