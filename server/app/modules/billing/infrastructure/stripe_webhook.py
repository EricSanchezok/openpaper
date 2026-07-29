import logging
from datetime import datetime

import stripe
from app.transport.http.public_v1.billing.config import (
    MONTHLY_PRICE_ID,
    STRIPE_WEBHOOK_SECRET,
    YEARLY_PRICE_ID,
    is_valid_price_id,
)
from app.modules.billing.infrastructure.stripe_webhook_ledger import (
    begin_webhook_attempt,
    complete_webhook,
    fail_webhook,
)
from app.modules.billing.infrastructure.subscription_repository import (
    subscription_repository,
)
from app.modules.identity.infrastructure.users import user_repository
from app.database.database import engine
from app.database.models import (
    StripeWebhookEventStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.database.telemetry import track_event
from app.helpers.email import (
    notify_billing_issue,
    send_confirmation_cancellation_email,
    send_subscription_welcome_email,
)
from app.modules.billing.infrastructure.stripe_client import construct_stripe_event
from app.helpers.advisory_locks import AdvisoryLock, AdvisoryLockNamespace
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _complete_noop(db: Session, *, event_id: str) -> dict[str, object]:
    complete_webhook(db, event_id=event_id)
    return {"success": True, "no_op": True}


def _ignore_event(db: Session, *, event_id: str) -> dict[str, object]:
    complete_webhook(
        db,
        event_id=event_id,
        status=StripeWebhookEventStatus.IGNORED,
    )
    return {"success": True, "ignored": True}


async def process_stripe_webhook(
    request: Request,
    stripe_signature: str,
    db: Session,
) -> dict[str, object]:
    """Handle Stripe webhook events for subscription management"""

    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=500, detail="Stripe webhook secret not configured"
        )

    event_id: str | None = None
    event_lock: AdvisoryLock | None = None
    ledger_started = False
    try:
        # Get the request body as bytes
        payload = await request.body()

        # Verify the webhook signature
        try:
            event = construct_stripe_event(
                payload, stripe_signature, STRIPE_WEBHOOK_SECRET
            )
        except Exception as e:
            logger.error(f"Invalid Stripe webhook signature: {e}")
            raise HTTPException(
                status_code=400, detail="Invalid Stripe webhook signature"
            )

        # Handle the event
        event_id = str(event["id"])
        event_type = str(event["type"])
        subscription: Subscription | None
        logger.info(f"Processing Stripe event: {event_type}")

        event_lock = AdvisoryLock(
            engine,
            namespace=AdvisoryLockNamespace.STRIPE_WEBHOOK,
            key=event_id,
        )
        if not event_lock.acquire():
            raise HTTPException(
                status_code=409,
                detail={"code": "stripe_webhook_in_progress"},
            )

        claim = begin_webhook_attempt(
            db,
            event_id=event_id,
            event_type=event_type,
        )
        ledger_started = True
        if not claim.should_process:
            return {"success": True, "duplicate": True}

        # Skip processing events that are not supported
        if event_type not in [
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
        ]:
            logger.info(f"Skipping unsupported event type: {event_type}")
            return _ignore_event(db, event_id=event_id)

        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            customer_id = session.customer
            subscription_id = session.subscription
            client_reference_id = session.client_reference_id

            if client_reference_id and customer_id:
                try:
                    logger.info(
                        f"Checkout completed for user {client_reference_id}, customer {customer_id}, subscription {subscription_id}"
                    )

                    track_event(
                        event_name="checkout_completed",
                        properties={
                            "user_id": client_reference_id,
                            "subscription_id": subscription_id,
                            "customer_id": customer_id,
                        },
                        db=db,
                    )

                except Exception as e:
                    logger.error(
                        f"Error processing checkout completion: {e}", exc_info=True
                    )

        elif event_type == "customer.subscription.created":
            stripe_sub = event["data"]["object"]
            subscription_id = stripe_sub.id
            customer_id = stripe_sub.customer

            try:
                stripe_received_price_id = None
                sub_items = stripe_sub["items"]["data"]
                if sub_items:
                    stripe_received_price_id = sub_items[0].price.id

                if stripe_received_price_id and not is_valid_price_id(
                    stripe_received_price_id
                ):
                    logger.info(
                        f"Skipping subscription creation for unsupported price ID: {stripe_received_price_id}"
                    )
                    return _ignore_event(db, event_id=event_id)

                # Try to find the user by customer ID
                existing_subscription = (
                    subscription_repository.get_by_stripe_customer_id(db, customer_id)
                )

                user_id: int | None = None
                if existing_subscription:
                    user_id = existing_subscription.user_id
                else:
                    try:
                        stripe_customer = stripe.Customer.retrieve(customer_id)
                        customer_email = stripe_customer.email

                        if customer_email:
                            user = user_repository.get_by_email(
                                db=db, email=customer_email
                            )

                            if user:
                                user_id = user.id
                                logger.info(
                                    f"Found user {user_id} by email {customer_email} for customer {customer_id}"
                                )
                            else:
                                logger.warning(
                                    f"No user found with email {customer_email} for customer {customer_id}"
                                )
                        else:
                            logger.warning(
                                f"No email found for Stripe customer {customer_id}"
                            )

                    except Exception:
                        logger.exception(
                            "Error retrieving Stripe customer %s", customer_id
                        )
                        raise

                if user_id:
                    webhook_sub_item = stripe_sub["items"]["data"][0]
                    subscription_data = {
                        "stripe_customer_id": customer_id,
                        "stripe_subscription_id": subscription_id,
                        "stripe_price_id": stripe_received_price_id,
                        "plan": SubscriptionPlan.RESEARCHER,
                        "status": stripe_sub.status,
                        "current_period_start": (
                            datetime.fromtimestamp(
                                webhook_sub_item.current_period_start
                            )
                            if getattr(webhook_sub_item, "current_period_start", None)
                            else None
                        ),
                        "current_period_end": (
                            datetime.fromtimestamp(webhook_sub_item.current_period_end)
                            if getattr(webhook_sub_item, "current_period_end", None)
                            else None
                        ),
                        "cancel_at_period_end": stripe_sub.cancel_at_period_end,
                    }

                    subscription = subscription_repository.create_or_update(
                        db, user_id, subscription_data
                    )

                    logger.info(
                        f"Subscription created for user {user_id} with ID {subscription_id}"
                    )

                    # Send welcome email
                    user = user_repository.get(db, id=user_id)
                    if user:
                        send_subscription_welcome_email(str(user.email))

                    track_event(
                        event_name="subscription_created",
                        properties={
                            "subscription_id": subscription_id,
                            "customer_id": customer_id,
                            "status": stripe_sub.status,
                        },
                        user_id=str(user_id),
                        db=db,
                    )

                else:
                    logger.warning(
                        f"Could not find user for customer {customer_id} when processing subscription.created"
                    )

            except Exception:
                logger.exception("Error processing subscription creation")
                raise

        elif event_type == "customer.subscription.updated":
            stripe_sub = event["data"]["object"]
            subscription_id = stripe_sub.id

            try:
                subscription = subscription_repository.get_by_stripe_subscription_id(
                    db, subscription_id
                )

                if subscription:
                    stripe_received_price_id = None
                    sub_items = stripe_sub["items"]["data"]
                    if sub_items:
                        stripe_received_price_id = sub_items[0].price.id

                    if stripe_received_price_id and not is_valid_price_id(
                        stripe_received_price_id
                    ):
                        logger.info(
                            f"Skipping subscription update for unsupported price ID: {stripe_received_price_id}"
                        )
                        return _ignore_event(db, event_id=event_id)

                    cancel_at_period_end = getattr(
                        stripe_sub, "cancel_at_period_end", False
                    )
                    cancel_at = getattr(stripe_sub, "cancel_at", None)
                    previous_cancel_at_period_end = subscription.cancel_at_period_end

                    is_scheduled_for_cancellation = cancel_at_period_end or (
                        cancel_at is not None
                    )
                    was_scheduled_for_cancellation = previous_cancel_at_period_end

                    updated_sub_item = stripe_sub["items"]["data"][0]

                    subscription_repository.update_subscription_status(
                        db,
                        subscription_id,
                        stripe_sub.status,
                        stripe_price_id=stripe_received_price_id,
                        period_start=(
                            datetime.fromtimestamp(
                                updated_sub_item.current_period_start
                            )
                            if getattr(updated_sub_item, "current_period_start", None)
                            else None
                        ),
                        period_end=(
                            datetime.fromtimestamp(updated_sub_item.current_period_end)
                            if getattr(updated_sub_item, "current_period_end", None)
                            else None
                        ),
                        cancel_at_period_end=is_scheduled_for_cancellation,
                    )

                    # Track subscription cancellation event when cancellation is newly scheduled
                    if (
                        is_scheduled_for_cancellation
                        and not was_scheduled_for_cancellation
                    ):
                        user_obj = user_repository.get(db, id=subscription.user_id)
                        if user_obj:
                            user_display_name = (
                                str(user_obj.display_name).split(" ")[0]
                                if user_obj.display_name
                                else None
                            )
                            send_confirmation_cancellation_email(
                                to_email=str(user_obj.email),
                                name=user_display_name,
                            )
                            track_event(
                                event_name="subscription_canceled",
                                properties={
                                    "subscription_id": subscription_id,
                                    "customer_id": stripe_sub.customer,
                                    "interval": (
                                        "yearly"
                                        if stripe_received_price_id == YEARLY_PRICE_ID
                                        else (
                                            "monthly"
                                            if stripe_received_price_id
                                            == MONTHLY_PRICE_ID
                                            else "unknown"
                                        )
                                    ),
                                    "canceled_at": (
                                        datetime.fromtimestamp(
                                            stripe_sub.canceled_at
                                        ).isoformat()
                                        if getattr(stripe_sub, "canceled_at", None)
                                        else None
                                    ),
                                    "cancel_at_period_end": True,
                                },
                                user_id=str(subscription.user_id),
                                db=db,
                            )
                        logger.info(
                            f"Subscription {subscription_id} scheduled for cancellation at period end"
                        )

                    logger.info(
                        f"Subscription {subscription_id} updated to status: {stripe_sub.status}"
                    )

            except Exception:
                logger.exception("Error updating subscription")
                raise

        elif event_type == "customer.subscription.deleted":
            stripe_sub = event["data"]["object"]
            subscription_id = stripe_sub.id

            try:
                subscription = subscription_repository.get_by_stripe_subscription_id(
                    db, subscription_id
                )

                if subscription:
                    stripe_received_price_id = None
                    sub_items = stripe_sub["items"]["data"]
                    if sub_items:
                        stripe_received_price_id = sub_items[0].price.id

                    if stripe_received_price_id and not is_valid_price_id(
                        stripe_received_price_id
                    ):
                        logger.info(
                            f"Skipping subscription deletion for unsupported price ID: {stripe_received_price_id}"
                        )
                        return _ignore_event(db, event_id=event_id)

                    # Downgrade to BASIC plan on cancellation
                    subscription_repository.update_subscription_status(
                        db,
                        subscription_id,
                        stripe_price_id=stripe_received_price_id,
                        status=SubscriptionStatus.CANCELED,
                        plan=SubscriptionPlan.BASIC,
                        cancel_at_period_end=True,
                    )

                    logger.info(f"Subscription {subscription_id} has been canceled")

                    track_event(
                        event_name="subscription_canceled",
                        properties={
                            "subscription_id": subscription_id,
                            "customer_id": stripe_sub.customer,
                            "interval": (
                                "yearly"
                                if stripe_received_price_id == YEARLY_PRICE_ID
                                else (
                                    "monthly"
                                    if stripe_received_price_id == MONTHLY_PRICE_ID
                                    else "unknown"
                                )
                            ),
                            "canceled_at": (
                                datetime.fromtimestamp(
                                    stripe_sub.canceled_at
                                ).isoformat()
                                if getattr(stripe_sub, "canceled_at", None)
                                else None
                            ),
                        },
                        user_id=str(subscription.user_id),
                        db=db,
                    )

            except Exception:
                logger.exception("Error canceling subscription")
                raise

        elif event_type == "invoice.payment_failed":
            invoice = event["data"]["object"]
            subscription_id = invoice.subscription
            customer_id = invoice.customer

            try:
                if subscription_id:
                    subscription = (
                        subscription_repository.get_by_stripe_subscription_id(
                            db, subscription_id
                        )
                    )

                    if subscription:
                        subscription_repository.update_subscription_status(
                            db, subscription_id, status=SubscriptionStatus.PAST_DUE
                        )

                        track_event(
                            event_name="payment_failed",
                            properties={
                                "subscription_id": subscription_id,
                                "customer_id": customer_id,
                                "invoice_id": invoice.id,
                            },
                            user_id=str(subscription.user_id),
                            db=db,
                        )

                        user = user_repository.get(db, id=subscription.user_id)

                        if not user:
                            logger.warning(
                                f"No user found for subscription {subscription_id} when processing payment failure"
                            )
                            raise LookupError(
                                f"Subscription user missing for {subscription_id}"
                            )

                        logger.warning(
                            f"Payment failed for subscription {subscription_id}, user {subscription.user_id}"
                        )

                        email_message = "Payment failed for your subscription. Please update your payment method"

                        notify_billing_issue(
                            str(user.email), email_message, str(user.display_name or "")
                        )

            except Exception:
                logger.exception("Error processing payment failure")
                raise

        elif event_type == "invoice.payment_succeeded":
            invoice = event["data"]["object"]
            subscription_id = invoice.subscription

            try:
                if subscription_id:
                    subscription = (
                        subscription_repository.get_by_stripe_subscription_id(
                            db, subscription_id
                        )
                    )

                    if subscription:
                        subscription_repository.update_subscription_status(
                            db, subscription_id, status=SubscriptionStatus.ACTIVE
                        )

                        track_event(
                            event_name="payment_succeeded",
                            properties={
                                "subscription_id": subscription_id,
                                "invoice_id": invoice.id,
                            },
                            user_id=str(subscription.user_id),
                            db=db,
                        )

                        logger.info(
                            f"Payment succeeded for subscription {subscription_id}"
                        )

            except Exception:
                logger.exception("Error processing payment success")
                raise

        elif event_type == "invoice.payment_action_required":
            invoice = event["data"]["object"]
            subscription_id = invoice.subscription

            try:
                if subscription_id:
                    subscription = (
                        subscription_repository.get_by_stripe_subscription_id(
                            db, subscription_id
                        )
                    )

                    if subscription:
                        track_event(
                            event_name="payment_action_required",
                            properties={
                                "subscription_id": subscription_id,
                                "invoice_id": invoice.id,
                            },
                            user_id=str(subscription.user_id),
                            db=db,
                        )

                        logger.info(
                            f"Payment action required for subscription {subscription_id}"
                        )

                        user = user_repository.get(db, id=subscription.user_id)
                        if not user:
                            logger.warning(
                                f"No user found for subscription {subscription_id} when processing payment action required"
                            )
                            raise LookupError(
                                f"Subscription user missing for {subscription_id}"
                            )

                        email_message = "Payment action required for your subscription. Please complete the required action."

                        notify_billing_issue(
                            str(user.email), email_message, str(user.display_name or "")
                        )

            except Exception:
                logger.exception("Error processing payment action required")
                raise

        elif event_type == "customer.subscription.past_due":
            stripe_sub = event["data"]["object"]
            subscription_id = stripe_sub.id

            try:
                subscription = subscription_repository.get_by_stripe_subscription_id(
                    db, subscription_id
                )

                if subscription:
                    subscription_repository.update_subscription_status(
                        db,
                        subscription_id,
                        status="past_due",
                    )

                    track_event(
                        event_name="subscription_past_due",
                        properties={
                            "user_id": str(subscription.user_id),
                            "subscription_id": subscription_id,
                        },
                        user_id=str(subscription.user_id),
                        db=db,
                    )

                    logger.warning(f"Subscription {subscription_id} is now past due")

                    user = user_repository.get(db, id=subscription.user_id)
                    if not user:
                        logger.warning(
                            f"No user found for subscription {subscription_id} when processing past due subscription"
                        )
                        raise LookupError(
                            f"Subscription user missing for {subscription_id}"
                        )
                    email_message = "Your subscription is past due. Please update your payment method to avoid service interruption."
                    notify_billing_issue(
                        str(user.email), email_message, str(user.display_name or "")
                    )

            except Exception:
                logger.exception("Error processing past due subscription")
                raise

        elif event_type in [
            "subscription_schedule.completed",
            "subscription_schedule.released",
        ]:
            schedule = event["data"]["object"]
            schedule_id = schedule.id
            subscription_id = schedule.subscription

            try:
                if subscription_id:
                    subscription = (
                        subscription_repository.get_by_stripe_subscription_id(
                            db, subscription_id
                        )
                    )

                    if (
                        subscription
                        and str(subscription.stripe_schedule_id) == schedule_id
                    ):
                        subscription_repository.create_or_update(
                            db,
                            subscription.user_id,
                            {"stripe_schedule_id": None},
                        )
                        logger.info(
                            f"Cleared schedule_id {schedule_id} from subscription {subscription_id} "
                            f"(event: {event_type})"
                        )
            except Exception:
                logger.exception(
                    "Error processing %s for schedule %s",
                    event_type,
                    schedule_id,
                )
                raise

        complete_webhook(db, event_id=event_id)
        return {"success": True}

    except HTTPException:
        db.rollback()
        if event_id is not None and ledger_started:
            fail_webhook(db, event_id=event_id, error_code="webhook_http_error")
        raise
    except Exception as e:
        db.rollback()
        if event_id is not None and ledger_started:
            fail_webhook(db, event_id=event_id, error_code="stripe_webhook_failed")
        logger.exception("Error processing Stripe webhook event %s", event_id)
        raise HTTPException(
            status_code=500,
            detail={"code": "stripe_webhook_failed"},
        ) from e
    finally:
        if event_lock is not None:
            event_lock.release()
