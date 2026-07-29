"""Generic terminal callback surface for every durable Jobs operation."""

import uuid

from app.bootstrap.container import build_job_callbacks
from app.database.database import get_db
from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
)
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

terminal_router = APIRouter()


@terminal_router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID,
    payload: dict[str, object],
    db: Session = Depends(get_db),
) -> object:
    return await build_job_callbacks(db=db).complete(job_id=job_id, payload=payload)


@terminal_router.post(
    "/jobs/{job_id}/fail",
    response_model=JobClaimResponse,
)
def fail_job(
    job_id: uuid.UUID,
    callback: JobFailureCallback,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return build_job_callbacks(db=db).fail(job_id=job_id, callback=callback)


@terminal_router.post("/schedules/zotero-sync")
def schedule_zotero_sync(
    threshold_seconds: int = Query(default=24 * 3600),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return build_job_callbacks(db=db).schedule_zotero_sync(
        threshold_seconds=threshold_seconds
    )
