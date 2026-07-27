"""Transactional Project deletion rules and storage cleanup."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from app.database.models import (
    Artifact,
    AudioOverview,
    AudioOverviewJob,
    Conversation,
    ConversableType,
    DataTableExtractionJob,
    Document,
    JobStatus,
    LibraryPaper,
    PaperImage,
    PaperUploadJob,
    Project,
    ProjectPaper,
)
from app.errors import AppError
from app.helpers.s3 import s3_service
from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


@dataclass(frozen=True, slots=True)
class ProjectDeletionPlan:
    orphan_documents: tuple[Document, ...]
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

    orphan_documents = tuple(
        db.scalars(
            select(Document)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(
                ProjectPaper.project_id == project.id,
                ~exists(
                    select(LibraryPaper.id).where(
                        LibraryPaper.document_id == Document.id
                    )
                ),
                ~exists(
                    select(ProjectPaper.id).where(
                        ProjectPaper.document_id == Document.id,
                        ProjectPaper.project_id != project.id,
                    )
                ),
            )
            .with_for_update()
        ).all()
    )

    storage_keys = {
        key
        for document in orphan_documents
        for key in (
            document.s3_object_key,
            document.parser_markdown_s3_key,
            document.parser_archive_s3_key,
        )
        if key
    }
    orphan_ids = [document.id for document in orphan_documents]
    if orphan_ids:
        storage_keys.update(
            db.scalars(
                select(PaperImage.s3_object_key).where(
                    PaperImage.paper_id.in_(orphan_ids)
                )
            ).all()
        )
    storage_keys.update(
        db.scalars(
            select(AudioOverview.s3_object_key).where(
                AudioOverview.conversable_type == ConversableType.PROJECT.value,
                AudioOverview.conversable_id == project.id,
            )
        ).all()
    )

    # Conversations are private user history, not Project-owned records. Keep
    # them, preserve a label snapshot, and remove the now-invalid scope.
    db.execute(
        update(Conversation)
        .where(
            Conversation.conversable_type == ConversableType.PROJECT.value,
            Conversation.conversable_id == project.id,
        )
        .values(
            conversable_type=ConversableType.EVERYTHING.value,
            conversable_id=None,
            scope_label_snapshot=func.coalesce(
                Conversation.scope_label_snapshot,
                project.title,
            ),
        )
    )
    # Artifacts are Project research outputs, so they follow the Project
    # lifecycle even though their polymorphic scope cannot carry a foreign key.
    db.execute(
        delete(Artifact).where(
            Artifact.scope_type == ConversableType.PROJECT.value,
            Artifact.scope_id == project.id,
        )
    )

    return ProjectDeletionPlan(
        orphan_documents=orphan_documents,
        storage_keys=tuple(sorted(storage_keys)),
    )


def delete_orphan_documents(
    db: Session,
    *,
    plan: ProjectDeletionPlan,
) -> None:
    """Delete canonical rows after the Project references have been flushed."""
    for document in plan.orphan_documents:
        db.delete(document)


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
