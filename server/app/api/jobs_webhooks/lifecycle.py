"""Lease callbacks shared by every durable Jobs operation."""

from __future__ import annotations

import uuid

from app.database.database import get_db
from app.repositories.jobs import job_repository
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

lifecycle_webhook_router = APIRouter()


class JobClaimResponse(BaseModel):
    claimed: bool


@lifecycle_webhook_router.post(
    "/jobs/{job_id}/claim",
    response_model=JobClaimResponse,
)
def claim_durable_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return JobClaimResponse(claimed=job_repository.claim(db, job_id=job_id) is not None)


@lifecycle_webhook_router.post(
    "/jobs/{job_id}/heartbeat",
    response_model=JobClaimResponse,
)
def heartbeat_durable_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    updated = job_repository.heartbeat(db, job_id=job_id)
    db.commit()
    return JobClaimResponse(claimed=updated)
