"""Cross-module canonical document submission and Jobs hand-off."""

from __future__ import annotations

import hashlib
import logging

from app.bootstrap.adapters.project_documents import (
    project_document_repository,
)
from app.database.models import (
    DocumentProcessingStatus,
    UploadReservation,
)
from app.helpers.s3 import document_source_key
from app.modules.papers.domain import can_begin_processing
from app.modules.papers.application.ingestion import IngestionFinalization
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.jobs.infrastructure.repository import job_repository
from app.shared.application import Actor
from app.helpers.celery_config import get_webhook_base_url
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def finalize_reserved_document(
    *,
    pdf_bytes: bytes,
    upload_job: UploadReservation,
    db: Session,
    user: Actor,
    skip_metadata_extraction: bool = False,
) -> IngestionFinalization:
    """Attach one upload to a content-addressed Document and process it once."""
    if not pdf_bytes:
        raise ValueError("pdf_bytes_cannot_be_empty")

    digest = hashlib.sha256(pdf_bytes).hexdigest()
    source_key = document_source_key(digest)
    filename = upload_job.original_filename or "document.pdf"
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
    changed = canonical.created or durable_job.document_id != document.id
    durable_job.document_id = document.id
    if durable_job.project_id is None:
        reference = document_repository.attach_library(
            db,
            document_id=document.id,
            user_id=user.id,
        )
        upload_job.reference_created = reference.created
        changed = changed or reference.created
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
        changed = changed or created

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.COMPLETED.value
    ):
        _job, job_completed = job_repository.complete(
            db,
            job_id=durable_job.id,
            result={"document_id": str(document.id), "reused": True},
        )
        db.flush()
        return IngestionFinalization(
            task_id=f"reused:{document.id}",
            job_id=durable_job.id,
            document_id=document.id,
            project_id=durable_job.project_id,
            changed=changed or job_completed,
            job_completed=job_completed,
        )

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.PROCESSING.value
        and document.processing_job_id != upload_job.id
    ):
        _job, job_completed = job_repository.complete(
            db,
            job_id=durable_job.id,
            result={
                "document_id": str(document.id),
                "reused": True,
                "processing_job_id": str(document.processing_job_id),
            },
        )
        db.flush()
        return IngestionFinalization(
            task_id=f"reused:{document.id}",
            job_id=durable_job.id,
            document_id=document.id,
            project_id=durable_job.project_id,
            changed=changed or job_completed,
            job_completed=job_completed,
        )

    if not canonical.created and not can_begin_processing(
        DocumentProcessingStatus(document.processing_status)
    ):
        raise RuntimeError("document_processing_transition_rejected")

    if (
        not canonical.created
        and document.processing_status == DocumentProcessingStatus.FAILED.value
    ):
        document_repository.mark_for_reprocessing(
            document,
            processing_job_id=upload_job.id,
        )
        changed = True

    if document.processing_status != DocumentProcessingStatus.PROCESSING.value:
        changed = True
    document.processing_status = DocumentProcessingStatus.PROCESSING.value
    document.processing_job_id = upload_job.id

    base_url = get_webhook_base_url().rstrip("/")
    durable_job.document_id = document.id
    durable_job.payload = {
        **durable_job.payload,
        "s3_object_key": document.s3_object_key,
        "skip_metadata_extraction": skip_metadata_extraction,
    }
    if durable_job.dispatch is None:
        job_repository.add_dispatch(
            db,
            job=durable_job,
            task_name="upload_and_process_file",
            queue="pdf_processing",
            kwargs={
                "s3_object_key": document.s3_object_key,
                "webhook_url": (
                    f"{base_url}/internal/v1/jobs/{upload_job.id}/complete"
                ),
                "claim_url": f"{base_url}/internal/v1/jobs/{upload_job.id}/claim",
                "skip_metadata_extraction": skip_metadata_extraction,
            },
        )
        changed = True
    db.flush()
    return IngestionFinalization(
        task_id=str(upload_job.id),
        job_id=durable_job.id,
        document_id=document.id,
        project_id=durable_job.project_id,
        changed=changed,
        job_completed=False,
    )
