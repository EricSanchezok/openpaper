"""Cross-module canonical document submission and Jobs hand-off."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

from app.bootstrap.adapters.project_documents import (
    project_document_repository,
)
from app.database.models import (
    DocumentProcessingStatus,
    UploadReservation,
)
from app.database.telemetry import track_event
from app.helpers.s3 import document_source_key, s3_service
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.jobs.infrastructure.repository import job_repository
from app.shared.application import Actor
from app.helpers.celery_config import get_webhook_base_url
from app.helpers.ai_limits import release_concurrency_by_id
from app.shared.domain import AppError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def submit_reserved_document(
    *,
    pdf_bytes: bytes,
    upload_job: UploadReservation,
    db: Session,
    user: Actor,
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
    durable_job = upload_job.job
    durable_job.document_id = document.id
    if durable_job.project_id is None:
        reference = document_repository.attach_library(
            db,
            document_id=document.id,
            user_id=user.id,
        )
        upload_job.reference_created = reference.created
    else:
        association, created = project_document_repository.attach_reserved_upload(
            db=db,
            document=document,
            upload_job=upload_job,
            user=user,
            project_id=durable_job.project_id,
        )
        del association
        upload_job.reference_created = created

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.COMPLETED.value
    ):
        job_repository.complete(
            db,
            job_id=durable_job.id,
            result={"document_id": str(document.id), "reused": True},
        )
        db.flush()
        return f"reused:{document.id}"

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.PROCESSING.value
        and document.processing_job_id != upload_job.id
    ):
        job_repository.complete(
            db,
            job_id=durable_job.id,
            result={
                "document_id": str(document.id),
                "reused": True,
                "processing_job_id": str(document.processing_job_id),
            },
        )
        db.flush()
        return f"reused:{document.id}"

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.FAILED.value
    ):
        document_repository.mark_for_reprocessing(
            document,
            processing_job_id=upload_job.id,
        )

    document.processing_status = DocumentProcessingStatus.PROCESSING.value
    document.processing_job_id = upload_job.id

    base_url = get_webhook_base_url().rstrip("/")
    durable_job.document_id = document.id
    durable_job.payload = {
        **durable_job.payload,
        "s3_object_key": document.s3_object_key,
        "skip_metadata_extraction": skip_metadata_extraction,
    }
    job_repository.add_dispatch(
        db,
        job=durable_job,
        task_name="upload_and_process_file",
        queue="pdf_processing",
        kwargs={
            "s3_object_key": document.s3_object_key,
            "webhook_url": (f"{base_url}/internal/v1/jobs/{upload_job.id}/complete"),
            "claim_url": f"{base_url}/internal/v1/jobs/{upload_job.id}/claim",
            "skip_metadata_extraction": skip_metadata_extraction,
        },
    )
    db.flush()
    return str(upload_job.id)


async def dispatch_reserved_document(
    *,
    pdf_bytes: bytes,
    upload_job: UploadReservation,
    db: Session,
    user: Actor,
) -> str:
    """Submit a reserved upload and close its concurrency lease on terminal paths."""
    try:
        task_id = await submit_reserved_document(
            pdf_bytes=pdf_bytes,
            upload_job=upload_job,
            db=db,
            user=user,
        )
        if task_id.startswith("reused:") or task_id != str(upload_job.id):
            await release_concurrency_by_id(
                user_id=int(user.id),
                category="background",
                operation_id=str(upload_job.id),
            )
        track_event(
            "paper_upload_submitted_to_microservice",
            properties={"task_id": task_id},
            user_id=str(user.id),
            db=db,
        )
        return task_id
    except Exception as exc:
        logger.error("Document processing job submission failed", exc_info=True)
        from app.modules.papers.infrastructure.upload_repository import (
            upload_reservation_repository,
        )

        upload_reservation_repository.mark_as_failed(
            db=db,
            job_id=str(upload_job.id),
            user=user,
            error_code="jobs_submission_failed",
        )
        await release_concurrency_by_id(
            user_id=int(user.id),
            category="background",
            operation_id=str(upload_job.id),
        )
        raise AppError(
            code="jobs_submission_failed",
            message="The document processing job could not be started",
            status_code=503,
        ) from exc
