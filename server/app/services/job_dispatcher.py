"""Recoverable transactional-outbox publisher for Jobs tasks."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from app.database.database import SessionLocal
from app.database.models import JobDispatchStatus
from app.integrations.jobs_client import jobs_client
from app.modules.jobs.infrastructure.repository import job_repository

logger = logging.getLogger(__name__)

DISPATCH_BATCH_SIZE = 20
DISPATCH_IDLE_SECONDS = float(os.getenv("JOB_DISPATCH_INTERVAL_SECONDS", "1"))
MAX_BACKOFF_SECONDS = 60


def dispatch_pending_jobs_once(*, limit: int = DISPATCH_BATCH_SIZE) -> int:
    """Publish a locked batch; failures remain pending with bounded backoff."""
    published_count = 0
    with SessionLocal() as db:
        recovered_count = job_repository.recover_expired_leases(db, limit=limit)
        if recovered_count:
            logger.warning(
                "Recovered expired Jobs leases",
                extra={"recovered_count": recovered_count},
            )
        dispatches = job_repository.pending_dispatches(db, limit=limit)
        for dispatch in dispatches:
            try:
                jobs_client.publish_task(
                    task_name=dispatch.task_name,
                    queue=dispatch.queue,
                    job_id=str(dispatch.job_id),
                    kwargs=dispatch.kwargs,
                )
            except RuntimeError as exc:
                dispatch.attempt_count += 1
                delay = min(
                    MAX_BACKOFF_SECONDS,
                    2 ** min(dispatch.attempt_count, 6),
                )
                dispatch.available_at = datetime.now(UTC) + timedelta(seconds=delay)
                dispatch.last_error_code = str(exc)
                dispatch.last_error_detail = type(exc).__name__
                logger.warning(
                    "Jobs outbox publish failed",
                    extra={
                        "job_id": str(dispatch.job_id),
                        "attempt": dispatch.attempt_count,
                        "error_code": dispatch.last_error_code,
                    },
                )
            else:
                dispatch.status = JobDispatchStatus.PUBLISHED.value
                dispatch.published_at = datetime.now(UTC)
                dispatch.last_error_code = None
                dispatch.last_error_detail = None
                published_count += 1
        db.commit()
    return published_count


async def run_job_dispatcher(stop: asyncio.Event) -> None:
    """Continuously drain the outbox without blocking the ASGI event loop."""
    while not stop.is_set():
        try:
            published = await asyncio.to_thread(dispatch_pending_jobs_once)
        except Exception:
            logger.exception("Jobs outbox dispatcher iteration failed")
            published = 0
        if published:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=DISPATCH_IDLE_SECONDS)
        except TimeoutError:
            pass
