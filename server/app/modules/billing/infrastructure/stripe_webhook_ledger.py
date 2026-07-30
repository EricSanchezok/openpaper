"""Persistence boundary for idempotent Stripe webhook delivery."""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.database.models import StripeWebhookEvent, StripeWebhookEventStatus
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class WebhookClaim:
    should_process: bool
    status: StripeWebhookEventStatus


def begin_webhook_attempt(
    db: Session, *, event_id: str, event_type: str
) -> WebhookClaim:
    event = db.get(StripeWebhookEvent, event_id)
    if event is not None and event.status in {
        StripeWebhookEventStatus.COMPLETED,
        StripeWebhookEventStatus.IGNORED,
    }:
        return WebhookClaim(
            should_process=False,
            status=StripeWebhookEventStatus(event.status),
        )

    if event is None:
        event = StripeWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            status=StripeWebhookEventStatus.PROCESSING,
            attempt_count=1,
        )
        db.add(event)
    else:
        event.event_type = event_type
        event.status = StripeWebhookEventStatus.PROCESSING
        event.attempt_count += 1
        event.last_error_code = None
        event.processed_at = None

    db.flush()
    return WebhookClaim(
        should_process=True,
        status=StripeWebhookEventStatus.PROCESSING,
    )


def complete_webhook(
    db: Session,
    *,
    event_id: str,
    status: StripeWebhookEventStatus = StripeWebhookEventStatus.COMPLETED,
) -> None:
    event = db.get(StripeWebhookEvent, event_id)
    if event is None:
        raise LookupError(f"Stripe webhook ledger row missing for {event_id}")
    event.status = status
    event.last_error_code = None
    event.processed_at = datetime.now(timezone.utc)
    db.flush()


def fail_webhook(db: Session, *, event_id: str, error_code: str) -> None:
    event = db.get(StripeWebhookEvent, event_id)
    if event is None:
        return
    event.status = StripeWebhookEventStatus.FAILED
    event.last_error_code = error_code[:64]
    event.processed_at = None
    db.flush()
