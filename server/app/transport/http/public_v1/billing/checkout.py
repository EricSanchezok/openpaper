import logging

import stripe
from app.modules.billing.application.contracts import SubscriptionInterval
from app.modules.billing.infrastructure.config import (
    MONTHLY_PRICE_ID,
    YEARLY_PRICE_ID,
    YOUR_DOMAIN,
)
from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.modules.billing.infrastructure.subscription_repository import (
    subscription_repository,
)
from app.database.database import get_db
from app.database.models import SubscriptionStatus
from app.database.telemetry import track_event
from app.shared.domain import AppError
from app.shared.application import Actor
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/checkout-sessions", status_code=status.HTTP_201_CREATED)
def create_checkout_session(
    interval: SubscriptionInterval,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> dict[str, str | None]:
    try:
        # Get or initialize customer ID
        subscription = subscription_repository.get_by_user_id(db, current_user.id)
        customer_id: str | None = None

        # Prevent duplicate subscriptions - if user already has an active or past_due subscription,
        # they should use the customer portal to manage it instead of creating a new one
        if subscription and subscription.status in [
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.TRIALING,
        ]:
            raise AppError(
                code="subscription_already_active",
                message="Use the customer portal to manage the active subscription",
                status_code=400,
            )

        # Cancel any incomplete Stripe subscription before creating a new checkout session
        # This handles the case where a user's first payment attempt failed
        if (
            subscription
            and subscription.status == SubscriptionStatus.INCOMPLETE
            and subscription.stripe_subscription_id
        ):
            try:
                stripe.Subscription.cancel(str(subscription.stripe_subscription_id))
                logger.info(
                    f"Canceled incomplete subscription {subscription.stripe_subscription_id} for user {current_user.id}"
                )
            except stripe.StripeError:
                logger.warning(
                    "Failed to cancel incomplete subscription %s",
                    subscription.stripe_subscription_id,
                    exc_info=True,
                )

        # Create a Stripe Checkout session
        price_id = (
            MONTHLY_PRICE_ID
            if interval == SubscriptionInterval.MONTHLY
            else YEARLY_PRICE_ID
        )

        if subscription and subscription.stripe_customer_id:
            customer_id = subscription.stripe_customer_id
        else:
            # Create a new customer in Stripe
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.display_name or current_user.email,
                metadata={"user_id": str(current_user.id)},
            )
            customer_id = customer.id

            # Store customer ID in database
            if not subscription:
                subscription_repository.create_or_update(
                    db, current_user.id, {"stripe_customer_id": customer_id}
                )

        if not price_id:
            raise AppError(
                code="stripe_price_not_configured",
                message="Subscription billing is not configured",
                status_code=503,
            )

        # Create session parameters
        session_params: stripe.checkout.Session.CreateParams = {
            "ui_mode": "embedded",
            "client_reference_id": str(current_user.id),
            "line_items": [{"quantity": 1, "price": price_id}],
            "mode": "subscription",
            "allow_promotion_codes": True,
            "return_url": f"{YOUR_DOMAIN}/subscribed?session_id={{CHECKOUT_SESSION_ID}}",
        }

        # Add telemetry
        track_event(
            event_name="checkout_initiated",
            properties={"interval": interval},
            user_id=str(current_user.id),
            db=db,
        )

        # Add customer if available
        if customer_id:
            session_params["customer"] = str(customer_id)

        session = stripe.checkout.Session.create(**session_params)

        return {"client_secret": session.client_secret}

    except stripe.StripeError as exc:
        logger.error("Error creating checkout session", exc_info=True)
        raise AppError(
            code="stripe_checkout_failed",
            message="The checkout session could not be created",
            status_code=502,
        ) from exc


@router.get("/checkout-sessions/{session_id}")
async def session_status(
    session_id: str,
    db: Session = Depends(get_db),
) -> dict[str, str | bool | None]:
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        customer_email = None
        backend_subscription_status = None
        backend_subscription_found = False

        if (
            hasattr(session, "customer_details")
            and session.customer_details is not None
        ):
            customer_email = session.customer_details.email

        # If the session is complete, also check our backend subscription status
        if session.status == "complete":
            # Get the client_reference_id which contains our user ID
            client_reference_id = session.client_reference_id
            subscription_id = session.subscription

            if client_reference_id:
                try:
                    # Check if we have the subscription in our database
                    user_id = int(client_reference_id)
                    subscription = subscription_repository.get_by_user_id(db, user_id)

                    if subscription and subscription.stripe_subscription_id:
                        backend_subscription_found = True
                        backend_subscription_status = (
                            str(subscription.status)
                            if subscription.status
                            else "unknown"
                        )

                        # Double-check that the subscription IDs match
                        if str(subscription.stripe_subscription_id) != subscription_id:
                            logger.warning(
                                f"Subscription ID mismatch for user {user_id}: "
                                f"session subscription {subscription_id} vs "
                                f"backend subscription {subscription.stripe_subscription_id}"
                            )
                    else:
                        logger.warning(
                            f"No subscription found in backend for user {user_id} "
                            f"despite completed checkout session {session_id}"
                        )

                except ValueError:
                    logger.error(
                        f"Invalid user ID in session client_reference_id: {client_reference_id}"
                    )
        return {
            "status": session.status,
            "customer_email": customer_email,
            "backend_subscription_found": backend_subscription_found,
            "backend_subscription_status": backend_subscription_status,
        }
    except stripe.StripeError as exc:
        raise AppError(
            code="stripe_session_unavailable",
            message="The checkout session could not be retrieved",
            status_code=502,
        ) from exc
