"""Operation-specific handlers behind the generic durable-job callback."""

from __future__ import annotations

import uuid

from app.modules.jobs.application.contracts import (
    JobCallbackIdentity,
    JobClaimResponse,
    PdfProcessingWebhookData,
    StorageDeleteCallback,
)
from app.modules.jobs.infrastructure import document_callbacks
from fastapi import Request
from sqlalchemy.orm import Session


def complete_pdf_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
) -> JobClaimResponse:
    return document_callbacks.complete_pdf_postprocess_job(job_id, callback, db)


def complete_document_gc_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
) -> JobClaimResponse:
    return document_callbacks.complete_document_gc_job(job_id, callback, db)


def complete_storage_delete_job(
    job_id: uuid.UUID,
    callback: StorageDeleteCallback,
    db: Session,
) -> JobClaimResponse:
    return document_callbacks.complete_storage_delete_job(job_id, callback, db)


async def handle_paper_processing_webhook(
    job_id: str,
    webhook_data: PdfProcessingWebhookData,
    db: Session,
) -> dict[str, object]:
    return await document_callbacks.handle_paper_processing_webhook(
        job_id,
        webhook_data,
        db,
    )


def schedule_zotero_jobs(
    request: Request,
    db: Session,
) -> dict[str, object]:
    return document_callbacks.schedule_zotero_jobs(request, db)


async def complete_zotero_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
) -> JobClaimResponse:
    return await document_callbacks.complete_zotero_postprocess_job(
        job_id,
        callback,
        db,
    )
