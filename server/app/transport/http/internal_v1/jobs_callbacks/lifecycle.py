"""Lease callbacks shared by every durable Jobs operation."""

import uuid
from typing import Annotated

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.jobs.application.authentication import VerifiedJobCallback
from app.modules.jobs.application.contracts import JobClaimResponse
from app.shared.application import ApplicationExecutor
from app.transport.http.internal_v1.authentication import verify_jobs_webhook
from fastapi import APIRouter, Depends

lifecycle_webhook_router = APIRouter()


@lifecycle_webhook_router.post(
    "/jobs/{job_id}/claim",
    response_model=JobClaimResponse,
)
def claim_durable_job(
    job_id: uuid.UUID,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobClaimResponse:
    return executor.command(
        lambda capabilities: capabilities.job_callbacks.claim(job_id=job_id)
    )


@lifecycle_webhook_router.post(
    "/jobs/{job_id}/heartbeat",
    response_model=JobClaimResponse,
)
def heartbeat_durable_job(
    job_id: uuid.UUID,
    _verified: Annotated[VerifiedJobCallback, Depends(verify_jobs_webhook)],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> JobClaimResponse:
    return executor.command(
        lambda capabilities: capabilities.job_callbacks.heartbeat(job_id=job_id)
    )
