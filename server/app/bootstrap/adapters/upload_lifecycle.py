"""Recovery and cleanup for durable PDF upload reservations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

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
from app.modules.papers.domain import can_fail_processing
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

logger = logging.getLogger(__name__)

UPLOAD_SUBMISSION_TIMEOUT = timedelta(minutes=15)
UPLOAD_PROCESSING_TIMEOUT = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class ReapedStaleUpload:
    job_id: UUID
    document_id: UUID | None
    project_id: UUID | None
    reference_removed: bool
    document_processing_failed: bool
    created_gc_job_id: UUID | None


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
    origin_operation_id: UUID,
    correlation_id: UUID,
    now: datetime | None = None,
) -> tuple[ReapedStaleUpload, ...]:
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
        return ()

    reaped: list[ReapedStaleUpload] = []
    for job in jobs:
        durable_job = job.job
        reference_removed = False
        document_processing_failed = False
        created_gc_job_id: UUID | None = None
        if durable_job.document_id is not None and job.reference_created:
            reference: LibraryPaper | ProjectPaper | None
            if durable_job.project_id is None:
                reference = db.scalar(
                    select(LibraryPaper)
                    .where(
                        LibraryPaper.document_id == durable_job.document_id,
                        LibraryPaper.user_id == durable_job.requested_by_id,
                    )
                    .with_for_update()
                )
            else:
                reference = db.scalar(
                    select(ProjectPaper)
                    .where(
                        ProjectPaper.document_id == durable_job.document_id,
                        ProjectPaper.project_id == durable_job.project_id,
                    )
                    .with_for_update()
                )
            if reference is not None:
                db.delete(reference)
                reference_removed = True
            db.flush()
            from app.bootstrap.adapters.document_gc import (
                schedule_document_gc,
            )

            scheduled = schedule_document_gc(
                db,
                document_id=durable_job.document_id,
                origin_operation_id=origin_operation_id,
                correlation_id=correlation_id,
            )
            if scheduled is not None and scheduled.created:
                created_gc_job_id = scheduled.job_id
        if durable_job.document_id is not None:
            document = db.scalar(
                select(Document)
                .where(Document.id == durable_job.document_id)
                .with_for_update()
            )
            if (
                document is not None
                and document.processing_job_id == job.id
                and can_fail_processing(
                    DocumentProcessingStatus(document.processing_status)
                )
            ):
                document.processing_status = DocumentProcessingStatus.FAILED.value
                document_processing_failed = True
        durable_job.status = JobStatus.FAILED.value
        durable_job.completed_at = current_time
        durable_job.error_code = (
            "upload_submission_timeout"
            if durable_job.dispatch is None
            else "upload_processing_timeout"
        )
        reaped.append(
            ReapedStaleUpload(
                job_id=durable_job.id,
                document_id=durable_job.document_id,
                project_id=durable_job.project_id,
                reference_removed=reference_removed,
                document_processing_failed=document_processing_failed,
                created_gc_job_id=created_gc_job_id,
            )
        )
    db.flush()
    return tuple(reaped)
