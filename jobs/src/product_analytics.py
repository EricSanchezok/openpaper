"""PostHog product analytics; never used for operational telemetry."""

from __future__ import annotations

import logging
import os
from typing import Any

from posthog import Posthog
from scholens_observability import log_event

POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", "")
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
posthog = (
    Posthog(POSTHOG_API_KEY, host="https://us.i.posthog.com", sync_mode=True)
    if POSTHOG_API_KEY
    else None
)
logger = logging.getLogger(__name__)

if DEBUG and posthog:
    posthog.debug = True


def track_event(
    event_name: str,
    distinct_id: str = "celery",
    properties: dict[str, Any] | None = None,
) -> None:
    if posthog is None or DEBUG:
        return
    try:
        posthog.capture(
            distinct_id=distinct_id,
            event=event_name,
            properties=properties or {},
        )
    except Exception as exc:
        log_event(
            logger,
            logging.WARNING,
            "product_analytics.delivery_failed",
            exc_info=exc,
            analytics_event=event_name,
        )
