"""Generic terminal callback surface for every durable Jobs operation."""

import uuid

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.bootstrap.execution import get_job_completion_processor
from app.bootstrap.adapters.job_completion_processor import JobCompletionProcessor
from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
)
from app.shared.application import ApplicationExecutor
from fastapi import APIRouter, Depends, Query

terminal_router = APIRouter()


@terminal_router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID,
    payload: dict[str, object],
    processor: JobCompletionProcessor = Depends(get_job_completion_processor),
) -> object:
    return await processor.complete(job_id=job_id, payload=payload)


@terminal_router.post(
    "/jobs/{job_id}/fail",
    response_model=JobClaimResponse,
)
def fail_job(
    job_id: uuid.UUID,
    callback: JobFailureCallback,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobClaimResponse:
    return executor.command(
        lambda capabilities: capabilities.job_callbacks.fail(
            job_id=job_id,
            callback=callback,
        )
    )


@terminal_router.post("/schedules/zotero-sync")
def schedule_zotero_sync(
    threshold_seconds: int = Query(default=24 * 3600),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> dict[str, int]:
    return executor.command(
        lambda capabilities: capabilities.job_callbacks.schedule_zotero_sync(
            threshold_seconds=threshold_seconds
        )
    )
