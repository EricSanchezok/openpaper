"""Atomic upload authorization and owner-paid resource reservation."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

from app.database.crud.paper_crud import paper_crud
from app.database.models import (
    Document,
    JobStatus,
    PaperUploadJob,
    Project,
    ProjectPaper,
)
from app.errors import AppError
from app.services.resource_quotas import (
    KB_SIZE_KEY,
    PAPER_UPLOAD_KEY,
    PROJECTS_KEY,
    PROJECT_PAPERS_KEY,
    get_plan_limits,
    get_quota_user,
    get_user_subscription_plan,
    lock_account_resource_quota,
)
from app.policies.projects import require_project_permission
from app.schemas.user import CurrentUser
from app.services.upload_lifecycle import (
    delete_upload_storage,
    reap_stale_uploads,
)
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

ACTIVE_UPLOAD_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


def _active_account_reservations(db: Session, *, owner_id: int) -> tuple[int, int]:
    row = db.execute(
        select(
            func.count(PaperUploadJob.id),
            func.coalesce(func.sum(PaperUploadJob.reserved_size_kb), 0),
        ).where(
            PaperUploadJob.quota_owner_id == owner_id,
            PaperUploadJob.status.in_(ACTIVE_UPLOAD_STATUSES),
        )
    ).one()
    return int(row[0]), int(row[1])


def _unattached_project_reservations(
    db: Session,
    *,
    project_id: UUID,
) -> int:
    return int(
        db.scalar(
            select(func.count(PaperUploadJob.id)).where(
                PaperUploadJob.project_id == project_id,
                PaperUploadJob.status.in_(ACTIVE_UPLOAD_STATUSES),
                ~exists(
                    select(Document.id).where(
                        Document.upload_job_id == PaperUploadJob.id
                    )
                ),
            )
        )
        or 0
    )


def reassign_project_quota_owner(
    db: Session,
    *,
    project: Project,
    new_owner_id: int,
) -> None:
    """Validate a transfer and move every active reservation to the new owner.

    The caller must hold a row lock on ``project``. Completed documents are
    charged only when they are not already present in the new owner's Library
    or another Project they own. In-progress uploads are represented solely by
    their durable reservations, so they are not counted twice.
    """
    lock_account_resource_quota(db, user_id=new_owner_id)
    owner = get_quota_user(db, user_id=new_owner_id)
    limits = get_plan_limits(get_user_subscription_plan(db, owner))

    owned_project_count = int(
        db.scalar(
            select(func.count(Project.id)).where(Project.owner_id == new_owner_id)
        )
        or 0
    )
    if owned_project_count + 1 > limits[PROJECTS_KEY]:
        raise AppError(
            code="project_transfer_quota_exceeded",
            message="The new owner has reached their Project limit",
            status_code=409,
        )

    project_document_count = int(
        db.scalar(
            select(func.count(ProjectPaper.id)).where(
                ProjectPaper.project_id == project.id
            )
        )
        or 0
    )
    if project_document_count > limits[PROJECT_PAPERS_KEY]:
        raise AppError(
            code="project_transfer_paper_quota_exceeded",
            message="This Project exceeds the new owner's per-Project paper limit",
            status_code=409,
        )

    project_active_count, project_active_size_kb = tuple(
        int(value)
        for value in db.execute(
            select(
                func.count(PaperUploadJob.id),
                func.coalesce(func.sum(PaperUploadJob.reserved_size_kb), 0),
            ).where(
                PaperUploadJob.project_id == project.id,
                PaperUploadJob.status.in_(ACTIVE_UPLOAD_STATUSES),
            )
        ).one()
    )
    existing_active_count, existing_active_size_kb = _active_account_reservations(
        db,
        owner_id=new_owner_id,
    )

    incremental_documents = list(
        db.scalars(
            select(Document)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .outerjoin(
                PaperUploadJob,
                PaperUploadJob.id == Document.upload_job_id,
            )
            .where(
                ProjectPaper.project_id == project.id,
                or_(
                    Document.upload_job_id.is_(None),
                    PaperUploadJob.status == JobStatus.COMPLETED,
                ),
                ~paper_crud.is_billed_to(new_owner_id),
            )
        ).all()
    )
    if any(document.size_in_kb is None for document in incremental_documents):
        raise AppError(
            code="project_transfer_storage_unavailable",
            message="Project storage is still being reconciled",
            status_code=409,
        )

    completed_count = paper_crud.get_total_paper_count(db=db, user=owner)
    if (
        completed_count
        + existing_active_count
        + len(incremental_documents)
        + project_active_count
        > limits[PAPER_UPLOAD_KEY]
    ):
        raise AppError(
            code="project_transfer_paper_quota_exceeded",
            message="The Project would exceed the new owner's paper limit",
            status_code=409,
        )

    if paper_crud.has_unknown_billed_document_size(db, user_id=new_owner_id):
        raise AppError(
            code="project_transfer_storage_unavailable",
            message="The new owner's storage usage is still being reconciled",
            status_code=409,
        )
    completed_size_kb = paper_crud.get_size_of_knowledge_base(db, user=owner)
    incremental_size_kb = sum(
        document.size_in_kb or 0 for document in incremental_documents
    )
    if (
        completed_size_kb
        + existing_active_size_kb
        + incremental_size_kb
        + project_active_size_kb
        > limits[KB_SIZE_KEY]
    ):
        raise AppError(
            code="project_transfer_storage_quota_exceeded",
            message="The Project would exceed the new owner's storage limit",
            status_code=409,
        )

    db.execute(
        update(PaperUploadJob)
        .where(
            PaperUploadJob.project_id == project.id,
            PaperUploadJob.status.in_(ACTIVE_UPLOAD_STATUSES),
        )
        .values(quota_owner_id=new_owner_id)
    )


def reserve_upload(
    db: Session,
    *,
    requester: CurrentUser,
    project_id: UUID | None,
    input_size_bytes: int,
    original_filename: str | None,
) -> PaperUploadJob:
    """Authorize once and persist the destination and quota owner before hand-off."""
    if input_size_bytes <= 0:
        raise AppError(
            code="empty_upload",
            message="The uploaded file is empty",
            status_code=400,
        )

    if project_id is None:
        owner_id = requester.id
        project = None
    else:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=requester.id,
            permission="manage_papers",
        )
        project = db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                status_code=404,
            )
        owner_id = project.owner_id

    lock_account_resource_quota(db, user_id=owner_id)
    cleanup_plan = reap_stale_uploads(db, quota_owner_id=owner_id)
    owner = get_quota_user(db, user_id=owner_id)
    limits = get_plan_limits(get_user_subscription_plan(db, owner))
    reserved_size_kb = math.ceil(input_size_bytes / 1024)
    reserved_count, active_size_kb = _active_account_reservations(
        db,
        owner_id=owner_id,
    )
    completed_count = paper_crud.get_total_paper_count(db=db, user=owner)
    if completed_count + reserved_count + 1 > limits[PAPER_UPLOAD_KEY]:
        raise AppError(
            code="paper_quota_exceeded",
            message="The account's paper limit has been reached",
            status_code=403,
        )

    if paper_crud.has_unknown_billed_document_size(db, user_id=owner_id):
        raise AppError(
            code="storage_usage_unavailable",
            message="Storage usage is still being reconciled",
            status_code=409,
        )
    completed_size_kb = paper_crud.get_size_of_knowledge_base(db, user=owner)
    if completed_size_kb + active_size_kb + reserved_size_kb > limits[KB_SIZE_KEY]:
        raise AppError(
            code="storage_quota_exceeded",
            message="The account's storage limit would be exceeded",
            status_code=403,
        )

    if project is not None:
        linked_count = int(
            db.scalar(
                select(func.count(ProjectPaper.id)).where(
                    ProjectPaper.project_id == project.id
                )
            )
            or 0
        )
        waiting_count = _unattached_project_reservations(
            db,
            project_id=project.id,
        )
        if linked_count + waiting_count + 1 > limits[PROJECT_PAPERS_KEY]:
            raise AppError(
                code="project_paper_quota_exceeded",
                message="The Project's paper limit has been reached",
                status_code=403,
            )

    job = PaperUploadJob(
        user_id=requester.id,
        quota_owner_id=owner_id,
        project_id=project_id,
        reserved_size_kb=reserved_size_kb,
        original_filename=original_filename,
        status=JobStatus.PENDING,
        started_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    delete_upload_storage(plan=cleanup_plan)
    return job
