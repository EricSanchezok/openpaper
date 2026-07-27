"""Recovery and cleanup for durable PDF upload reservations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.database.models import (
    Document,
    JobStatus,
    LibraryPaper,
    PaperImage,
    PaperUploadJob,
    ProjectPaper,
)
from app.helpers.s3 import s3_service
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

    job_ids = [job.id for job in jobs]
    documents = list(
        db.scalars(
            select(Document)
            .where(Document.upload_job_id.in_(job_ids))
            .with_for_update()
        ).all()
    )
    document_ids = [document.id for document in documents]
    storage_keys = {
        key
        for document in documents
        for key in (
            document.s3_object_key,
            document.parser_markdown_s3_key,
            document.parser_archive_s3_key,
        )
        if key
    }
    if document_ids:
        storage_keys.update(
            db.scalars(
                select(PaperImage.s3_object_key).where(
                    PaperImage.paper_id.in_(document_ids)
                )
            ).all()
        )
        db.execute(
            delete(LibraryPaper).where(LibraryPaper.document_id.in_(document_ids))
        )
        db.execute(
            delete(ProjectPaper).where(ProjectPaper.document_id.in_(document_ids))
        )
        db.flush()
        for document in documents:
            db.delete(document)

    for job in jobs:
        job.status = JobStatus.FAILED
        job.completed_at = current_time
        job.error_code = (
            "upload_submission_timeout"
            if job.task_id is None
            else "upload_processing_timeout"
        )

    return UploadCleanupPlan(storage_keys=tuple(sorted(storage_keys)))


def delete_upload_storage(*, plan: UploadCleanupPlan) -> None:
    """Best-effort object deletion after the caller commits the timeout cleanup."""
    failures = 0
    for key in plan.storage_keys:
        try:
            if not s3_service.delete_file(object_key=key):
                failures += 1
        except Exception:
            failures += 1
            logger.exception("Failed to delete timed-out upload object %s", key)
    if failures:
        logger.error(
            "Timed-out upload cleanup left %d S3 objects for lifecycle cleanup",
            failures,
        )
