import logging
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from src.product_analytics import track_event

logger = logging.getLogger(__name__)


@asynccontextmanager
async def time_it(
    description: str,
    job_id: str | None = None,
    event_properties: dict[str, Any] | None = None,
) -> AsyncIterator[None]:
    """Measure one async operation and emit its duration even when it fails."""
    start_time = time.monotonic()
    logger.info("job.operation.started", extra={"operation": description})
    try:
        yield
    finally:
        duration = time.monotonic() - start_time
        logger.info(
            "job.operation.completed",
            extra={
                "operation": description,
                "duration_seconds": round(duration, 3),
            },
        )
        if job_id:
            event_name = f"timer:{description.lower().replace(' ', '_')}"
            properties = {"duration": duration, **(event_properties or {})}
            track_event(event_name, distinct_id=job_id, properties=properties)
