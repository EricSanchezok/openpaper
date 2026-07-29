"""Recovery and cleanup for durable PDF upload reservations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    DurableJob,
    JobDispatch,
    JobStatus,
    LibraryPaper,
    UploadReservation,
    ProjectPaper,
)
from sqlalchemy import and_, delete, exists, or_, select
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
            ~exists(
                select(JobDispatch.id).where(
                    JobDispatch.job_id == DurableJob.id,
                )
            ),
            DurableJob.created_at >= now - UPLOAD_SUBMISSION_TIMEOUT,
        ),
        and_(
            exists(
                select(JobDispatch.id).where(
                    JobDispatch.job_id == DurableJob.id,
                )
            ),
            DurableJob.created_at >= now - UPLOAD_PROCESSING_TIMEOUT,
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
            select(UploadReservation)
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                UploadReservation.quota_owner_id == quota_owner_id,
                DurableJob.status.in_((JobStatus.PENDING, JobStatus.RUNNING)),
                ~active_upload_freshness_clause(current_time),
            )
            .with_for_update(skip_locked=True)
        ).all()
    )
    if not jobs:
        return UploadCleanupPlan()

    for job in jobs:
        durable_job = job.job
        if durable_job.document_id is not None and job.reference_created:
            if durable_job.project_id is None:
                db.execute(
                    delete(LibraryPaper).where(
                        LibraryPaper.document_id == durable_job.document_id,
                        LibraryPaper.user_id == durable_job.requested_by_id,
                    )
                )
            else:
                db.execute(
                    delete(ProjectPaper).where(
                        ProjectPaper.document_id == durable_job.document_id,
                        ProjectPaper.project_id == durable_job.project_id,
                    )
                )
            db.flush()
            from app.modules.papers.infrastructure.garbage_collection import (
                schedule_document_gc,
            )

            schedule_document_gc(db, document_id=durable_job.document_id)
        if durable_job.document_id is not None:
            document = db.scalar(
                select(Document)
                .where(Document.id == durable_job.document_id)
                .with_for_update()
            )
            if document is not None and document.processing_job_id == job.id:
                document.processing_status = DocumentProcessingStatus.FAILED.value
        durable_job.status = JobStatus.FAILED.value
        durable_job.completed_at = current_time
        durable_job.error_code = (
            "upload_submission_timeout"
            if durable_job.dispatch is None
            else "upload_processing_timeout"
        )

    return UploadCleanupPlan()


def delete_upload_storage(*, plan: UploadCleanupPlan) -> None:
    """Canonical object cleanup is owned exclusively by delayed Document GC."""
    del plan
