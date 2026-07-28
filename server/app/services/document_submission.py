"""Canonical PDF ingestion and deterministic Jobs hand-off."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timezone

from app.database.crud.projects.project_paper_crud import project_paper_crud
from app.database.models import (
    DocumentProcessingStatus,
    JobOperation,
    JobStatus,
    PaperUploadJob,
)
from app.database.telemetry import track_event
from app.helpers.s3 import document_source_key, s3_service
from app.repositories.documents import document_repository
from app.repositories.jobs import EnqueueJob, job_repository
from app.schemas.user import CurrentUser
from app.helpers.celery_config import get_webhook_base_url
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def submit_reserved_document(
    *,
    pdf_bytes: bytes,
    upload_job: PaperUploadJob,
    db: Session,
    user: CurrentUser,
    skip_metadata_extraction: bool = False,
) -> str:
    """Attach one upload to a content-addressed Document and process it once."""
    if not pdf_bytes:
        raise ValueError("pdf_bytes_cannot_be_empty")

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    source_key = document_source_key(digest)
    filename = upload_job.original_filename or "document.pdf"
    existing = document_repository.get_by_sha256(db, sha256=digest)

    if existing is None:
        upload_started_at = time.monotonic()
        await asyncio.to_thread(
            s3_service.upload_document_source,
            sha256=digest,
            pdf_bytes=pdf_bytes,
        )
        track_event(
            "timer:canonical_pdf_upload",
            user_id=str(user.id),
            properties={
                "duration": time.monotonic() - upload_started_at,
                "job_id": str(upload_job.id),
                "sha256": digest,
            },
            sync=True,
            db=db,
        )

    canonical = document_repository.get_or_create(
        db,
        sha256=digest,
        original_filename=filename,
        mime_type="application/pdf",
        size_bytes=len(pdf_bytes),
        s3_object_key=source_key,
        created_by_id=user.id,
        processing_job_id=upload_job.id,
    )
    document = canonical.document
    upload_job.document_id = document.id

    if upload_job.project_id is None:
        reference = document_repository.attach_library(
            db,
            document_id=document.id,
            user_id=user.id,
        )
        upload_job.reference_created = reference.created
    else:
        association, created = project_paper_crud.attach_reserved_upload(
            db=db,
            document=document,
            upload_job=upload_job,
            user=user,
            project_id=upload_job.project_id,
            auto_commit=False,
        )
        del association
        upload_job.reference_created = created

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.COMPLETED.value
    ):
        upload_job.status = JobStatus.COMPLETED.value
        upload_job.completed_at = datetime.now(timezone.utc)
        upload_job.task_id = None
        db.commit()
        return f"reused:{document.id}"

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.PROCESSING.value
        and document.processing_job_id != upload_job.id
    ):
        upload_job.status = JobStatus.RUNNING.value
        upload_job.task_id = str(document.processing_job_id)
        db.commit()
        return str(document.processing_job_id)

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.FAILED.value
    ):
        document_repository.mark_for_reprocessing(
            document,
            processing_job_id=upload_job.id,
        )

    upload_job.status = JobStatus.RUNNING.value
    upload_job.task_id = str(upload_job.id)
    document.processing_status = DocumentProcessingStatus.PROCESSING.value
    document.processing_job_id = upload_job.id
    db.commit()

    base_url = get_webhook_base_url().rstrip("/")
    job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.PDF_PROCESS,
            requested_by_id=user.id,
            project_id=upload_job.project_id,
            document_id=document.id,
            idempotency_key=f"pdf-ingest:{upload_job.id}",
            payload={
                "s3_object_key": document.s3_object_key,
                "skip_metadata_extraction": skip_metadata_extraction,
            },
            task_name="upload_and_process_file",
            queue="pdf_processing",
            task_kwargs={
                "s3_object_key": document.s3_object_key,
                "webhook_url": (
                    f"{base_url}/api/webhooks/paper-processing/{upload_job.id}"
                ),
                "claim_url": (
                    f"{base_url}/api/webhooks/jobs/{upload_job.id}/claim"
                ),
                "skip_metadata_extraction": skip_metadata_extraction,
            },
            job_id=upload_job.id,
        ),
    )
    db.commit()
    return str(upload_job.id)
