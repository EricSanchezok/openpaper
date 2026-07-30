"""Generic terminal callback surface for every durable Jobs operation."""

import uuid
from typing import Annotated

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.bootstrap.execution import get_job_completion_processor
from app.bootstrap.execution import get_operation_context_factory
from app.bootstrap.adapters.job_completion_processor import JobCompletionProcessor
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
)
from app.shared.application import (
    ApplicationExecutor,
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)
from app.transport.http.internal_v1.authentication import verify_jobs_webhook
from fastapi import APIRouter, Depends, Query

terminal_router = APIRouter()


@terminal_router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID,
    payload: dict[str, object],
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    processor: JobCompletionProcessor = Depends(get_job_completion_processor),
) -> object:
    return await processor.complete(
        job_id=job_id,
        payload=payload,
        verified=verified,
    )


@terminal_router.post(
    "/jobs/{job_id}/fail",
    response_model=JobClaimResponse,
)
def fail_job(
    job_id: uuid.UUID,
    callback: JobFailureCallback,
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    processor: JobCompletionProcessor = Depends(get_job_completion_processor),
) -> JobClaimResponse:
    return processor.fail(
        job_id=job_id,
        callback=callback,
        verified=verified,
    )


@terminal_router.post("/schedules/zotero-sync")
def schedule_zotero_sync(
    verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    threshold_seconds: int = Query(default=24 * 3600),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> dict[str, int]:
    operation = operation_factory.root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin(
            task_name="zotero_sync",
            run_id=verified.request_id,
        ),
        credential=None,
    )
    return executor.command(
        lambda capabilities: capabilities.job_callbacks.schedule_zotero_sync(
            operation=operation, threshold_seconds=threshold_seconds
        )
    )
