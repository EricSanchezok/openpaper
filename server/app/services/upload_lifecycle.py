"""Recovery and cleanup for durable PDF upload reservations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    JobStatus,
    LibraryPaper,
    PaperUploadJob,
    ProjectPaper,
)
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

logger = logging.getLogger(__name__)

UPLOAD_SUBMISSION_TIMEOUT = timedelta(minutes=15)
UPLOAD_PROCESSING_TIMEOUT = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class UploadCleanupPlan:
    storage_keys: tuple[str, ...] = ()


def active_upload_freshness_clause(now: datetime) -> ColumnElement[bool]:
    """Shared definition of which active upload rows are still live."""
    return or_(
        and_(
            PaperUploadJob.task_id.is_(None),
            PaperUploadJob.created_at >= now - UPLOAD_SUBMISSION_TIMEOUT,
        ),
        and_(
            PaperUploadJob.task_id.isnot(None),
            PaperUploadJob.created_at >= now - UPLOAD_PROCESSING_TIMEOUT,
        ),
    )


def reap_stale_uploads(
    db: Session,
    *,
    quota_owner_id: int,
    now: datetime | None = None,
) -> UploadCleanupPlan:
    """Fail timed-out jobs and remove their inaccessible placeholder documents.

    The caller owns the transaction and must already hold the account quota
    advisory lock. Rows are locked with ``SKIP LOCKED`` so concurrent quota
    checks never process the same timeout twice.
    """
    current_time = now or datetime.now(timezone.utc)
    jobs = list(
        db.scalars(
            select(PaperUploadJob)
            .where(
                PaperUploadJob.quota_owner_id == quota_owner_id,
                PaperUploadJob.status.in_((JobStatus.PENDING, JobStatus.RUNNING)),
                ~active_upload_freshness_clause(current_time),
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    if not jobs:
        return UploadCleanupPlan()

    for job in jobs:
        if job.document_id is not None and job.reference_created:
            if job.project_id is None:
                db.execute(
                    delete(LibraryPaper).where(
                        LibraryPaper.document_id == job.document_id,
                        LibraryPaper.user_id == job.user_id,
                    )
                )
            else:
                db.execute(
                    delete(ProjectPaper).where(
                        ProjectPaper.document_id == job.document_id,
                        ProjectPaper.project_id == job.project_id,
                    )
                )
            db.flush()
            from app.services.document_gc import schedule_document_gc

            schedule_document_gc(db, document_id=job.document_id)
        if job.document_id is not None:
            document = db.scalar(
                select(Document).where(Document.id == job.document_id).with_for_update()
            )
            if document is not None and document.processing_job_id == job.id:
                document.processing_status = DocumentProcessingStatus.FAILED.value
        job.status = JobStatus.FAILED
        job.completed_at = current_time
        job.error_code = (
            "upload_submission_timeout"
            if job.task_id is None
            else "upload_processing_timeout"
        )

    return UploadCleanupPlan()


def delete_upload_storage(*, plan: UploadCleanupPlan) -> None:
    """Canonical object cleanup is owned exclusively by delayed Document GC."""
    del plan
