"""Lease callbacks shared by every durable Jobs operation."""

import uuid

from app.bootstrap.container import build_job_callbacks
from app.database.database import get_db
from app.modules.jobs.application.contracts import JobClaimResponse
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

lifecycle_webhook_router = APIRouter()


@lifecycle_webhook_router.post(
    "/jobs/{job_id}/claim",
    response_model=JobClaimResponse,
)
def claim_durable_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return build_job_callbacks(db=db).claim(job_id=job_id)


@lifecycle_webhook_router.post(
    "/jobs/{job_id}/heartbeat",
    response_model=JobClaimResponse,
)
def heartbeat_durable_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return build_job_callbacks(db=db).heartbeat(job_id=job_id)
