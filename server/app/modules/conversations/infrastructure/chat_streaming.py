"""Stable error boundary for HTTP streams that have already started."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from app.database.telemetry import track_event

logger = logging.getLogger(__name__)


async def stream_with_stable_error(
    source: AsyncIterator[str],
    *,
    delimiter: str,
    event_name: str,
    user_id: int,
    properties: dict[str, object],
) -> AsyncIterator[str]:
    """Convert post-header failures to one public stream error event."""
    try:
        async for event in source:
            yield event
    except Exception as exc:
        track_event(
            event_name,
            properties={
                **properties,
                "error_type": type(exc).__name__,
            },
            user_id=str(user_id),
        )
        logger.exception("Chat stream failed after response headers were sent")
        yield f"{json.dumps({'type': 'error', 'content': 'chat_failed'})}{delimiter}"
