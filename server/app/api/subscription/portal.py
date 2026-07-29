import logging

import stripe
from app.api.subscription.config import MONTHLY_PRICE_ID, YEARLY_PRICE_ID, YOUR_DOMAIN
from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.crud.subscription_crud import subscription_crud
from app.database.database import get_db
from app.database.telemetry import track_event
from app.errors import AppError
from app.shared.application import Actor
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/create-portal-session")
def create_customer_portal_session(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> dict[str, str | None]:
    """Create a Stripe customer portal session for the current user"""
    try:
        subscription = subscription_crud.get_by_user_id(db, current_user.id)

        if not subscription or not subscription.stripe_customer_id:
            raise AppError(
                code="stripe_customer_not_found",
                message="No billing account is available for this user",
                status_code=400,
            )

        portal_session = stripe.billing_portal.Session.create(
            customer=str(subscription.stripe_customer_id),
            return_url=f"{YOUR_DOMAIN}/pricing",
        )

        return {"url": portal_session.url}

    except stripe.StripeError as exc:
        logger.error("Error creating customer portal session", exc_info=True)
        raise AppError(
            code="stripe_portal_failed",
            message="The billing portal could not be opened",
            status_code=502,
        ) from exc


@router.post("/resubscribe")
def resubscribe(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> dict[str, str | bool]:
    """
    Reactivate a canceled subscription or reverse a scheduled cancellation.

    This endpoint handles two scenarios:
    1. If subscription is scheduled for cancellation (cancel_at_period_end=true),
       it will reverse the cancellation by setting cancel_at_period_end=false
    2. If subscription is already canceled, it will create a new subscription
       using the existing customer and payment method
    """
    subscription = subscription_crud.get_by_user_id(db, current_user.id)

    if not subscription:
        return {
            "success": False,
            "error": "No existing subscription found. Please create a new subscription instead.",
        }

    if not subscription.stripe_customer_id:
        return {
            "success": False,
            "error": "No Stripe customer ID found. Please create a new subscription instead.",
        }

    if not subscription.stripe_subscription_id:
        return {
            "success": False,
            "error": "No Stripe subscription found. Please create a new subscription instead.",
        }

    try:
        subscription_id = str(subscription.stripe_subscription_id)

        # Check if the Stripe subscription still exists and is canceled
        stripe_sub = stripe.Subscription.retrieve(subscription_id)

        if stripe_sub.status == "canceled":
            logger.info(
                f"Subscription {stripe_sub.id} is already canceled, creating new subscription"
            )

            # Try to get the payment method from the previous subscription
            payment_method_id = None
            try:
                customer = stripe.Customer.retrieve(
                    str(subscription.stripe_customer_id)
                )
                invoice_settings = getattr(customer, "invoice_settings", None)
                if (
                    invoice_settings is not None
                    and invoice_settings.default_payment_method
                ):
                    payment_method_id = invoice_settings.default_payment_method

                if not payment_method_id and getattr(
                    stripe_sub, "default_payment_method", None
                ):
                    payment_method_id = stripe_sub.default_payment_method

                if not payment_method_id:
                    payment_methods = stripe.PaymentMethod.list(
                        customer=str(subscription.stripe_customer_id), type="card"
                    )
                    if payment_methods.data:
                        payment_method_id = payment_methods.data[0].id

            except stripe.StripeError:
                logger.warning(
                    "Could not retrieve a payment method for customer %s",
                    subscription.stripe_customer_id,
                    exc_info=True,
                )
                return {
                    "success": False,
                    "error": "no_payment_method",
                    "message": "No payment method available. Please use the checkout flow to add a payment method and resubscribe.",
                    "redirect_to_checkout": True,
                }

            stripe_price_id = str(subscription.stripe_price_id)
            if not stripe_price_id:
                return {
                    "success": False,
                    "error": "no_price_id",
                    "message": "No price ID found for the subscription. Please contact support.",
                    "redirect_to_checkout": True,
                }

            subscription_params: stripe.Subscription.CreateParams = {
                "customer": str(subscription.stripe_customer_id),
                "items": [{"price": stripe_price_id}],
                "metadata": {"user_id": str(current_user.id)},
            }

            if payment_method_id:
                subscription_params["default_payment_method"] = payment_method_id

            try:
                new_stripe_sub = stripe.Subscription.create(**subscription_params)

                track_event(
                    event_name="subscription_reactivated_new",
                    properties={
                        "old_subscription_id": str(subscription.stripe_subscription_id),
                        "new_subscription_id": new_stripe_sub.id,
                        "customer_id": str(subscription.stripe_customer_id),
                        "interval": (
                            "yearly"
                            if stripe_price_id == YEARLY_PRICE_ID
                            else (
                                "monthly"
                                if stripe_price_id == MONTHLY_PRICE_ID
                                else "unknown"
                            )
                        ),
                    },
                    user_id=str(current_user.id),
                    db=db,
                )

                logger.info(
                    f"Created new subscription {new_stripe_sub.id} for user {current_user.id}"
                )
                return {"success": True, "subscription_id": new_stripe_sub.id}

            except stripe.StripeError as stripe_error:
                error_message = str(stripe_error).lower()
                if any(
                    keyword in error_message
                    for keyword in ["card", "declined", "insufficient", "payment"]
                ):
                    logger.warning(
                        f"Payment error during resubscription for user {current_user.id}: {stripe_error}"
                    )
                    return {
                        "success": False,
                        "error": "payment_failed",
                        "message": "Your payment method was declined. Please update your payment method and try again.",
                        "redirect_to_checkout": True,
                    }
                else:
                    raise stripe_error

        elif stripe_sub.cancel_at_period_end:
            logger.info(
                f"Subscription {stripe_sub.id} is scheduled for cancellation, reversing cancellation"
            )

            updated_sub = stripe.Subscription.modify(
                str(subscription.stripe_subscription_id), cancel_at_period_end=False
            )

            logger.info(f"Reversed cancellation for subscription {updated_sub.id}")

            track_event(
                event_name="subscription_cancellation_reversed",
                properties={
                    "subscription_id": str(subscription.stripe_subscription_id),
                    "customer_id": str(subscription.stripe_customer_id),
                },
                user_id=str(current_user.id),
                db=db,
            )

            logger.info(
                f"Reversed cancellation for subscription {stripe_sub.id} for user {current_user.id}"
            )
            return {
                "success": True,
                "subscription_id": str(subscription.stripe_subscription_id),
                "action": "cancellation_reversed",
                "message": "Your subscription cancellation has been reversed and will continue.",
            }

        else:
            logger.info(f"Subscription {stripe_sub.id} is active, no action needed")
            return {
                "success": True,
                "subscription_id": str(subscription.stripe_subscription_id),
                "action": "no_action",
                "message": "Your subscription is still active.",
            }

    except stripe.StripeError as stripe_error:
        if (
            "no attached payment source" in str(stripe_error).lower()
            or "default payment method" in str(stripe_error).lower()
        ):
            logger.info(
                f"No payment method available for customer {subscription.stripe_customer_id}, redirecting to checkout"
            )
            return {
                "success": False,
                "error": "no_payment_method",
                "message": "No payment method available. Please use the checkout flow to add a payment method and resubscribe.",
                "redirect_to_checkout": True,
            }
        else:
            logger.error(
                f"Error retrieving Stripe subscription {subscription.stripe_subscription_id}: {stripe_error}",
                exc_info=True,
            )
            return {
                "success": False,
                "error": "Previous subscription not found in Stripe",
            }
