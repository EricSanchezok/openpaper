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
    JobStatus,
    PaperUploadJob,
)
from app.database.telemetry import track_event
from app.helpers.s3 import document_source_key, s3_service
from app.integrations.jobs_client import jobs_client
from app.repositories.documents import document_repository
from app.schemas.user import CurrentUser
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

    try:
        return jobs_client.submit_pdf_processing_job(
            document.s3_object_key,
            str(upload_job.id),
            skip_metadata_extraction,
        )
    except Exception:
        db.rollback()
        locked_job = db.get(PaperUploadJob, upload_job.id)
        locked_document = document_repository.get_by_sha256(
            db,
            sha256=digest,
            for_update=True,
        )
        if locked_job is not None:
            locked_job.status = JobStatus.FAILED.value
            locked_job.error_code = "jobs_submission_failed"
            locked_job.completed_at = datetime.now(timezone.utc)
        if (
            locked_document is not None
            and locked_document.processing_job_id == upload_job.id
        ):
            locked_document.processing_status = DocumentProcessingStatus.FAILED.value
        db.commit()
        logger.exception("Canonical PDF job publication failed for %s", upload_job.id)
        raise RuntimeError("pdf_upload_submission_failed") from None
