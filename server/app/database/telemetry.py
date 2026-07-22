import logging
import os
from typing import Any, Optional

from app.database.crud.subscription_crud import subscription_crud
from app.database.database import SessionLocal
from posthog import Posthog
from sqlalchemy.exc import InvalidRequestError, OperationalError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", None)
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

posthog = (
    Posthog(
        POSTHOG_API_KEY,
        host="https://us.i.posthog.com",
        enable_exception_autocapture=True,
    )
    if POSTHOG_API_KEY
    else None
)

posthog_sync = (
    Posthog(
        POSTHOG_API_KEY,
        host="https://us.i.posthog.com",
        sync_mode=True,
        enable_exception_autocapture=True,
    )
    if POSTHOG_API_KEY
    else None
)

if DEBUG and posthog:
    posthog.debug = True


def _lookup_subscription(db: Optional[Session], user_id: int):
    """
    Look up a user's subscription for event enrichment.

    Prefer the request-scoped session when available so we don't check out an
    extra connection per event. If it's been closed or left in a bad state
    (PendingRollbackError, ResourceClosedError, and similar all subclass
    InvalidRequestError), silently fall back to a fresh session — telemetry
    should never take down the caller's flow.
    """
    if db is not None:
        try:
            return subscription_crud.get_by_user_id(db, user_id=user_id)
        except (InvalidRequestError, OperationalError) as e:
            logger.warning(
                "track_event: provided db session unusable (%s); falling back",
                type(e).__name__,
            )

    try:
        with SessionLocal() as fresh_db:
            return subscription_crud.get_by_user_id(fresh_db, user_id=user_id)
    except Exception as e:
        logger.warning("track_event: subscription lookup failed: %s", e)
        return None


def track_event(
    event_name: str,
    properties: Optional[dict[str, Any]] = None,
    user_id: Optional[str] = None,
    sync: bool = False,
    db: Optional[Session] = None,
) -> None:
    """
    Track an event with PostHog.

    :param event_name: Name of the event to track.
    :param properties: Optional dictionary of properties to associate with the event.
    :param user_id: User ID to associate with the event, or None for anonymous.
    :param sync: If True, send the event synchronously (blocks until sent).
    :param db: Optional request-scoped session to reuse for the subscription
               lookup. Falls back to a fresh session if None or unusable.
    """
    event_properties = dict(properties or {})
    if POSTHOG_API_KEY and posthog and posthog_sync and not DEBUG:
        subscription = None
        if user_id is None:
            user_id = "anonymous"
        else:
            try:
                subscription = _lookup_subscription(db, int(user_id))
            except (TypeError, ValueError):
                logger.warning("track_event: invalid user id %r", user_id)

            if subscription:
                event_properties.update(
                    {
                        "subscription_plan": subscription.plan,
                        "subscription_status": subscription.status,
                    }
                )
            else:
                event_properties.update(
                    {
                        "subscription_plan": None,
                        "subscription_status": None,
                    }
                )

        if sync:
            posthog_sync.capture(
                distinct_id=user_id, event=event_name, properties=event_properties
            )
        else:
            posthog.capture(
                distinct_id=user_id, event=event_name, properties=event_properties
            )
    else:
        print(
            f"PostHog tracking disabled. Event: {event_name}, Properties: {event_properties}"
        )
