"""Generic terminal callback surface for every durable Jobs operation."""

from __future__ import annotations

import uuid
from typing import Any

from app.database.database import get_db
from app.database.models import JobOperation
from app.errors import AppError
from app.modules.jobs.application.contracts import (
    AudioOverviewWebhookData,
    DataTableWebhookData,
    JobCallbackIdentity,
    JobClaimResponse,
    JobFailureCallback,
    PdfProcessingWebhookData,
    StorageDeleteCallback,
)
from app.modules.jobs.infrastructure.repository import job_repository
from app.transport.http.internal_v1.jobs_callbacks import documents, research
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.orm import Session

terminal_router = APIRouter()


def _validated(model: type[Any], payload: dict[str, object]) -> Any:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise AppError(
            code="job_callback_invalid",
            message="Job callback payload is invalid for its operation",
            status_code=422,
        ) from exc


@terminal_router.post("/jobs/{job_id}/complete")
async def complete_job(
    job_id: uuid.UUID,
    payload: dict[str, object],
    db: Session = Depends(get_db),
) -> object:
    """Dispatch a terminal result using the persisted operation discriminator."""
    operation = JobOperation(job_repository.require(db, job_id=job_id).operation)
    if operation == JobOperation.PDF_PROCESS:
        return await documents.handle_paper_processing_webhook(
            str(job_id),
            _validated(PdfProcessingWebhookData, payload),
            db,
        )
    if operation == JobOperation.PDF_POSTPROCESS:
        return documents.complete_pdf_postprocess_job(
            job_id, _validated(JobCallbackIdentity, payload), db
        )
    if operation == JobOperation.DOCUMENT_GC:
        return documents.complete_document_gc_job(
            job_id, _validated(JobCallbackIdentity, payload), db
        )
    if operation == JobOperation.STORAGE_DELETE:
        return documents.complete_storage_delete_job(
            job_id, _validated(StorageDeleteCallback, payload), db
        )
    if operation == JobOperation.ZOTERO_POSTPROCESS:
        return await documents.complete_zotero_postprocess_job(
            job_id, _validated(JobCallbackIdentity, payload), db
        )
    if operation == JobOperation.AUDIO_GENERATE:
        return await research.complete_audio_job(
            job_id, _validated(AudioOverviewWebhookData, payload), db
        )
    if operation == JobOperation.DATA_TABLE_GENERATE:
        return await research.complete_data_table_job(
            job_id, _validated(DataTableWebhookData, payload), db
        )
    raise AppError(
        code="job_operation_unsupported",
        message="Job operation has no callback handler",
        status_code=409,
    )


@terminal_router.post(
    "/jobs/{job_id}/fail",
    response_model=JobClaimResponse,
)
async def fail_job(
    job_id: uuid.UUID,
    callback: JobFailureCallback,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    if callback.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback ID does not match",
            status_code=409,
        )
    _, changed = job_repository.fail(
        db,
        job_id=job_id,
        error_code=callback.error_code,
    )
    return JobClaimResponse(claimed=changed)


@terminal_router.post("/integrations/zotero/schedule")
def schedule_zotero_jobs(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return documents.schedule_zotero_jobs(request, db)
