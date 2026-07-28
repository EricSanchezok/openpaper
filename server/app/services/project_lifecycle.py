"""Transactional Project deletion rules and storage cleanup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.database.models import (
    AudioOverview,
    AudioOverviewJob,
    Conversation,
    ConversationScopeType,
    ConversableType,
    DataTableExtractionJob,
    JobStatus,
    PaperUploadJob,
    Project,
    ProjectPaper,
)
from app.errors import AppError
from app.helpers.s3 import s3_service
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class ProjectDeletionPlan:
    candidate_document_ids: tuple[UUID, ...]
    storage_keys: tuple[str, ...]


def _active_project_job_count(db: Session, *, project_id: UUID) -> int:
    statements = (
        select(PaperUploadJob.id).where(
            PaperUploadJob.project_id == project_id,
            PaperUploadJob.status.in_(ACTIVE_JOB_STATUSES),
        ),
        select(AudioOverviewJob.id).where(
            AudioOverviewJob.conversable_type == ConversableType.PROJECT.value,
            AudioOverviewJob.conversable_id == project_id,
            AudioOverviewJob.status.in_(ACTIVE_JOB_STATUSES),
        ),
        select(DataTableExtractionJob.id).where(
            DataTableExtractionJob.project_id == project_id,
            DataTableExtractionJob.status.in_(ACTIVE_JOB_STATUSES),
        ),
    )
    return sum(
        len(db.scalars(statement.with_for_update()).all()) for statement in statements
    )


def prepare_project_deletion(
    db: Session,
    *,
    project: Project,
) -> ProjectDeletionPlan:
    """Apply all database-side deletion semantics inside the caller's transaction."""
    if _active_project_job_count(db, project_id=project.id):
        raise AppError(
            code="project_has_active_jobs",
            message="Wait for active Project jobs to finish before deleting it",
            status_code=409,
        )

    candidate_document_ids = tuple(
        db.scalars(
            select(ProjectPaper.document_id).where(
                ProjectPaper.project_id == project.id
            )
        ).all()
    )
    storage_keys: set[str] = set()
    storage_keys.update(
        db.scalars(
            select(AudioOverview.s3_object_key).where(
                AudioOverview.conversable_type == ConversableType.PROJECT.value,
                AudioOverview.conversable_id == project.id,
            )
        ).all()
    )

    # Conversations are private user history, not Project-owned records. Mark
    # the context as deleted before the Project FK becomes NULL on cascade.
    db.execute(
        update(Conversation)
        .where(
            Conversation.scope_type == ConversationScopeType.PROJECT.value,
            Conversation.project_id == project.id,
        )
        .values(
            scope_label_snapshot=func.coalesce(
                Conversation.scope_label_snapshot,
                project.title,
            ),
            context_deleted_at=func.now(),
        )
    )
    return ProjectDeletionPlan(
        candidate_document_ids=candidate_document_ids,
        storage_keys=tuple(sorted(storage_keys)),
    )


def schedule_orphan_documents(
    db: Session,
    *,
    plan: ProjectDeletionPlan,
) -> None:
    """Schedule canonical cleanup after ProjectPaper cascades have been flushed."""
    from app.services.document_gc import schedule_document_gc

    for document_id in plan.candidate_document_ids:
        schedule_document_gc(db, document_id=document_id)


def delete_project_storage(*, plan: ProjectDeletionPlan) -> None:
    """Best-effort object cleanup after the database transaction commits."""
    failed_keys: list[str] = []
    for key in plan.storage_keys:
        try:
            if not s3_service.delete_file(object_key=key):
                failed_keys.append(key)
        except Exception:
            logger.exception("Failed to delete Project storage object %s", key)
            failed_keys.append(key)
    if failed_keys:
        logger.error(
            "Project deletion left %d S3 objects for lifecycle cleanup",
            len(failed_keys),
        )
