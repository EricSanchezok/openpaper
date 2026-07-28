"""HTTP bindings for durable document and Zotero callbacks."""

from __future__ import annotations

import uuid

from app.database.database import get_db
from app.schemas.jobs import (
    JobCallbackIdentity,
    JobClaimResponse,
    PdfParserUpgradeWebhookData,
    PdfProcessingWebhookData,
    StorageDeleteCallback,
)
from app.services import document_callbacks
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

document_webhook_router = APIRouter()


@document_webhook_router.post(
    "/jobs/{job_id}/pdf-postprocess",
    response_model=JobClaimResponse,
)
def complete_pdf_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return document_callbacks.complete_pdf_postprocess_job(job_id, callback, db)


@document_webhook_router.post(
    "/jobs/{job_id}/document-gc",
    response_model=JobClaimResponse,
)
def complete_document_gc_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return document_callbacks.complete_document_gc_job(job_id, callback, db)


@document_webhook_router.post(
    "/jobs/{job_id}/storage-delete",
    response_model=JobClaimResponse,
)
def complete_storage_delete_job(
    job_id: uuid.UUID,
    callback: StorageDeleteCallback,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return document_callbacks.complete_storage_delete_job(job_id, callback, db)


@document_webhook_router.post("/paper-processing/{job_id}")
async def handle_paper_processing_webhook(
    job_id: str,
    webhook_data: PdfProcessingWebhookData,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return await document_callbacks.handle_paper_processing_webhook(
        job_id,
        webhook_data,
        db,
    )


@document_webhook_router.post("/jobs/{job_id}/pdf-upgrade")
def handle_paper_parser_upgrade_webhook(
    job_id: uuid.UUID,
    webhook_data: PdfParserUpgradeWebhookData,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return document_callbacks.handle_paper_parser_upgrade_webhook(
        job_id,
        webhook_data,
        db,
    )


@document_webhook_router.post("/internal/zotero-schedule")
def schedule_zotero_jobs(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return document_callbacks.schedule_zotero_jobs(request, db)


@document_webhook_router.post(
    "/jobs/{job_id}/zotero-postprocess",
    response_model=JobClaimResponse,
)
async def complete_zotero_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return await document_callbacks.complete_zotero_postprocess_job(
        job_id,
        callback,
        db,
    )
