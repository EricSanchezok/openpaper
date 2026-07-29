"""Transactional Project deletion rules and storage cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.database.models import (
    Conversation,
    ConversationScopeType,
    DurableJob,
    JobStatus,
    Project,
    ProjectPaper,
    ResearchAudioOverview,
    ResearchItem,
    ResearchScopeType,
)
from app.errors import AppError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class ProjectDeletionPlan:
    candidate_document_ids: tuple[UUID, ...]
    storage_keys: tuple[str, ...]


def _active_project_job_count(db: Session, *, project_id: UUID) -> int:
    statements = (
        select(DurableJob.id).where(
            DurableJob.project_id == project_id,
            DurableJob.status.in_(ACTIVE_JOB_STATUSES),
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
            select(ResearchAudioOverview.s3_object_key)
            .join(
                ResearchItem,
                ResearchItem.id == ResearchAudioOverview.research_item_id,
            )
            .where(
                ResearchItem.scope_type == ResearchScopeType.PROJECT.value,
                ResearchItem.project_id == project.id,
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
    from app.modules.papers.infrastructure.garbage_collection import schedule_document_gc

    for document_id in plan.candidate_document_ids:
        schedule_document_gc(db, document_id=document_id)


def schedule_project_storage_cleanup(
    db: Session,
    *,
    project_id: UUID,
    plan: ProjectDeletionPlan,
) -> None:
    from app.modules.papers.infrastructure.storage_cleanup import schedule_storage_deletion

    schedule_storage_deletion(
        db,
        object_keys=plan.storage_keys,
        idempotency_key=f"project:{project_id}",
    )
