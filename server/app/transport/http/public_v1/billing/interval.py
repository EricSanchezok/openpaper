import logging
from datetime import datetime, timezone

import stripe
from app.transport.http.public_v1.billing.config import (
    MONTHLY_PRICE_ID,
    YEARLY_PRICE_ID,
    SubscriptionInterval,
)
from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.crud.subscription_crud import subscription_crud
from app.database.database import get_db
from app.database.telemetry import track_event
from app.helpers.email import notify_converted_billing_interval
from app.errors import AppError
from app.shared.application import Actor
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/change-interval")
def change_subscription_interval(
    new_interval: SubscriptionInterval,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> dict[str, object]:
    """
    Schedule a billing interval change at the end of the current billing period
    using Stripe Subscription Schedules. No immediate charge or proration.
    """
    subscription = subscription_crud.get_by_user_id(db, current_user.id)

    if not subscription:
        return {"success": False, "error": "No existing subscription found"}

    if not subscription.stripe_subscription_id:
        return {"success": False, "error": "No Stripe subscription ID found"}

    subscription_id = str(subscription.stripe_subscription_id)

    stripe_sub = stripe.Subscription.retrieve(subscription_id)

    if stripe_sub.status not in ["active", "trialing"]:
        raise AppError(
            code="subscription_interval_unavailable",
            message="The billing interval cannot be changed for this subscription",
            status_code=400,
        )

    if MONTHLY_PRICE_ID is None or YEARLY_PRICE_ID is None:
        raise AppError(
            code="stripe_price_not_configured",
            message="Subscription billing is not configured",
            status_code=503,
        )

    new_price_id: str = (
        MONTHLY_PRICE_ID
        if new_interval == SubscriptionInterval.MONTHLY
        else YEARLY_PRICE_ID
    )

    current_price_id = stripe_sub["items"]["data"][0]["price"]["id"]

    if current_price_id == new_price_id:
        return {
            "success": False,
            "message": f"Subscription is already on {new_interval.value}ly billing",
        }

    current_period_end_ts = getattr(
        stripe_sub["items"]["data"][0], "current_period_end", None
    )

    # If there's already a schedule, release it first
    if subscription.stripe_schedule_id:
        try:
            stripe.SubscriptionSchedule.release(str(subscription.stripe_schedule_id))
        except stripe.StripeError:
            logger.warning(
                "Failed to release existing schedule %s",
                subscription.stripe_schedule_id,
                exc_info=True,
            )

    # Create a schedule from the existing subscription
    try:
        schedule = stripe.SubscriptionSchedule.create(from_subscription=subscription_id)

        current_phase = schedule.phases[0]
        stripe.SubscriptionSchedule.modify(
            schedule.id,
            end_behavior="release",
            phases=[
                {
                    "items": [{"price": current_price_id, "quantity": 1}],
                    "start_date": current_phase.start_date,
                    "end_date": current_phase.end_date,
                },
                {
                    "items": [{"price": new_price_id, "quantity": 1}],
                },
            ],
        )

        subscription_crud.create_or_update(
            db,
            current_user.id,
            {"stripe_schedule_id": schedule.id},
        )

    except stripe.StripeError as exc:
        logger.error("Error creating subscription schedule", exc_info=True)
        raise AppError(
            code="subscription_interval_failed",
            message="The subscription interval change could not be scheduled",
            status_code=502,
        ) from exc

    effective_ts = current_period_end_ts or current_phase.end_date
    effective_date = datetime.fromtimestamp(effective_ts, tz=timezone.utc)

    track_event(
        event_name="subscription_interval_scheduled",
        properties={
            "subscription_id": subscription_id,
            "schedule_id": schedule.id,
            "old_interval": (
                "yearly" if current_price_id == YEARLY_PRICE_ID else "monthly"
            ),
            "new_interval": new_interval.value + "ly",
            "effective_date": effective_date.isoformat(),
        },
        user_id=str(current_user.id),
        db=db,
    )

    logger.info(
        f"Subscription {subscription_id} for user {current_user.id} scheduled to change from "
        f"{'yearly' if current_price_id == YEARLY_PRICE_ID else 'monthly'} to "
        f"{new_interval.value}ly on {effective_date}"
    )

    notify_converted_billing_interval(
        email=current_user.email,
        new_interval=new_interval.value,
        name=current_user.display_name,
    )

    return {
        "success": True,
        "message": f"Subscription interval will change to {new_interval.value}ly on {effective_date.strftime('%B %d, %Y')}",
        "scheduled_date": effective_date.isoformat(),
        "new_interval": new_interval.value,
    }


@router.post("/cancel-scheduled-change")
def cancel_scheduled_change(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> dict[str, object]:
    """
    Cancel a previously scheduled billing interval change.
    Releases the Stripe Subscription Schedule so the subscription continues as-is.
    """
    subscription = subscription_crud.get_by_user_id(db, current_user.id)

    if not subscription:
        return {"success": False, "error": "No existing subscription found"}

    if not subscription.stripe_schedule_id:
        return {"success": False, "error": "No scheduled change found"}

    schedule_id = str(subscription.stripe_schedule_id)

    try:
        stripe.SubscriptionSchedule.release(schedule_id)
    except stripe.StripeError as exc:
        logger.error(
            "Error releasing subscription schedule %s",
            schedule_id,
            exc_info=True,
        )
        raise AppError(
            code="subscription_schedule_cancel_failed",
            message="The scheduled subscription change could not be canceled",
            status_code=502,
        ) from exc

    subscription_crud.create_or_update(
        db, current_user.id, {"stripe_schedule_id": None}
    )

    track_event(
        event_name="subscription_interval_schedule_canceled",
        properties={
            "subscription_id": str(subscription.stripe_subscription_id),
            "schedule_id": schedule_id,
        },
        user_id=str(current_user.id),
        db=db,
    )

    logger.info(
        f"Canceled scheduled interval change (schedule {schedule_id}) for user {current_user.id}"
    )

    return {
        "success": True,
        "message": "Scheduled billing change has been canceled",
    }
