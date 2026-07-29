"""Cross-module upload authorization and owner-paid resource reservation."""

from __future__ import annotations

import math
from uuid import UUID, uuid4

from app.modules.billing.infrastructure.usage_repository import (
    resource_usage_repository,
)
from app.database.models import (
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    LibraryPaper,
    UploadReservation,
    Project,
    ProjectPaper,
)
from app.shared.domain import AppError
from app.modules.billing.infrastructure.quotas import (
    KB_SIZE_KEY,
    PAPER_UPLOAD_KEY,
    PROJECTS_KEY,
    PROJECT_PAPERS_KEY,
    get_plan_limits,
    get_quota_user,
    get_user_subscription_plan,
    lock_account_resource_quota,
)
from app.modules.projects.infrastructure.access import require_project_permission
from app.shared.application import Actor
from app.modules.jobs.infrastructure.repository import CreateJob, job_repository
from app.bootstrap.adapters.upload_lifecycle import (
    reap_stale_uploads,
)
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

ACTIVE_UPLOAD_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


def _active_account_reservations(db: Session, *, owner_id: int) -> tuple[int, int]:
    row = db.execute(
        select(
            func.coalesce(func.sum(UploadReservation.reserved_reference_count), 0),
            func.coalesce(func.sum(UploadReservation.reserved_size_kb), 0),
        )
        .join(DurableJob, DurableJob.id == UploadReservation.id)
        .where(
            UploadReservation.quota_owner_id == owner_id,
            DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
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
            select(
                func.coalesce(func.sum(UploadReservation.reserved_reference_count), 0)
            )
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                DurableJob.project_id == project_id,
                DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
                DurableJob.document_id.is_(None),
            )
        )
        or 0
    )


def _has_active_duplicate_reservation(
    db: Session,
    *,
    requester_id: int,
    project_id: UUID | None,
    content_sha256: str,
) -> bool:
    """Detect an in-flight upload to the same logical collection.

    The caller holds the quota owner's account lock, so this check and the
    reservation insert are serialized across personal and Project uploads.
    """
    statement = (
        select(func.count(UploadReservation.id))
        .join(DurableJob, DurableJob.id == UploadReservation.id)
        .where(
            UploadReservation.content_sha256 == content_sha256,
            DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
        )
    )
    if project_id is None:
        statement = statement.where(
            DurableJob.project_id.is_(None),
            DurableJob.requested_by_id == requester_id,
        )
    else:
        statement = statement.where(DurableJob.project_id == project_id)
    return bool(db.scalar(statement))


def reassign_project_quota_owner(
    db: Session,
    *,
    project: Project,
    new_owner_id: int,
) -> None:
    """Validate a transfer and move every active reservation to the new owner.

    The caller must hold a row lock on ``project``. Every logical ProjectPaper
    reference is billed even when the same Document also exists in the new
    owner's Library or another owned Project. In-progress uploads are
    represented by their durable reservations.
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
                func.count(UploadReservation.id),
                func.coalesce(func.sum(UploadReservation.reserved_size_kb), 0),
            )
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                DurableJob.project_id == project.id,
                DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
            )
        ).one()
    )
    existing_active_count, existing_active_size_kb = _active_account_reservations(
        db,
        owner_id=new_owner_id,
    )

    project_documents = list(
        db.scalars(
            select(Document)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(
                ProjectPaper.project_id == project.id,
                Document.processing_status == "completed",
            )
        ).all()
    )

    completed_count = resource_usage_repository.completed_reference_count(
        db, user_id=owner.id
    )
    if (
        completed_count
        + existing_active_count
        + project_document_count
        + project_active_count
        > limits[PAPER_UPLOAD_KEY]
    ):
        raise AppError(
            code="project_transfer_paper_quota_exceeded",
            message="The Project would exceed the new owner's paper limit",
            status_code=409,
        )

    completed_size_kb = resource_usage_repository.completed_storage_kb(
        db, user_id=owner.id
    )
    incremental_size_kb = sum(
        (document.size_bytes + 1023) // 1024 for document in project_documents
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
        update(UploadReservation)
        .where(
            UploadReservation.id.in_(
                select(DurableJob.id).where(
                    DurableJob.project_id == project.id,
                    DurableJob.status.in_(ACTIVE_UPLOAD_STATUSES),
                )
            ),
        )
        .values(quota_owner_id=new_owner_id)
    )


def reserve_upload(
    db: Session,
    *,
    requester: Actor,
    project_id: UUID | None,
    input_size_bytes: int,
    original_filename: str | None,
    content_sha256: str,
    idempotency_key: str | None = None,
) -> UploadReservation:
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
    durable_idempotency_key = (
        f"pdf-ingestion:{requester.id}:{project_id or 'library'}:{idempotency_key}"
        if idempotency_key is not None
        else None
    )
    if durable_idempotency_key is not None:
        existing_job = job_repository.find_by_idempotency_key(
            db,
            idempotency_key=durable_idempotency_key,
        )
        if existing_job is not None:
            same_request = (
                existing_job.requested_by_id == requester.id
                and existing_job.project_id == project_id
                and existing_job.payload.get("content_sha256") == content_sha256
            )
            existing_reservation = db.get(UploadReservation, existing_job.id)
            if not same_request or existing_reservation is None:
                raise AppError(
                    code="idempotency_key_reused",
                    message="The idempotency key was already used for another request",
                    status_code=409,
                )
            return existing_reservation

    existing_document_id = db.scalar(
        select(Document.id).where(Document.sha256 == content_sha256)
    )
    if existing_document_id is None:
        reference_already_exists = False
    elif project_id is None:
        reference_already_exists = bool(
            db.scalar(
                select(func.count(LibraryPaper.id)).where(
                    LibraryPaper.user_id == requester.id,
                    LibraryPaper.document_id == existing_document_id,
                )
            )
        )
    else:
        reference_already_exists = bool(
            db.scalar(
                select(func.count(ProjectPaper.id)).where(
                    ProjectPaper.project_id == project_id,
                    ProjectPaper.document_id == existing_document_id,
                )
            )
        )
    if reference_already_exists:
        raise AppError(
            code=(
                "document_already_in_project"
                if project_id is not None
                else "document_already_in_library"
            ),
            message="This document is already in the selected collection",
            status_code=409,
        )

    reap_stale_uploads(db, quota_owner_id=owner_id)
    if _has_active_duplicate_reservation(
        db,
        requester_id=requester.id,
        project_id=project_id,
        content_sha256=content_sha256,
    ):
        raise AppError(
            code="document_upload_in_progress",
            message="This document is already being uploaded to this collection",
            status_code=409,
        )
    owner = get_quota_user(db, user_id=owner_id)
    limits = get_plan_limits(get_user_subscription_plan(db, owner))
    reserved_reference_count = 0 if reference_already_exists else 1
    reserved_size_kb = (
        0 if reference_already_exists else math.ceil(input_size_bytes / 1024)
    )
    reserved_count, active_size_kb = _active_account_reservations(
        db,
        owner_id=owner_id,
    )
    completed_count = resource_usage_repository.completed_reference_count(
        db, user_id=owner.id
    )
    if (
        completed_count + reserved_count + reserved_reference_count
        > limits[PAPER_UPLOAD_KEY]
    ):
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if project is not None
                else "paper_quota_exceeded"
            ),
            message="The account's paper limit has been reached",
            status_code=403,
        )

    completed_size_kb = resource_usage_repository.completed_storage_kb(
        db, user_id=owner.id
    )
    if completed_size_kb + active_size_kb + reserved_size_kb > limits[KB_SIZE_KEY]:
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if project is not None
                else "storage_quota_exceeded"
            ),
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
        if (
            linked_count + waiting_count + reserved_reference_count
            > limits[PROJECT_PAPERS_KEY]
        ):
            raise AppError(
                code="project_paper_quota_exceeded",
                message="The Project's paper limit has been reached",
                status_code=403,
            )

    job_id = uuid4()
    durable_job = job_repository.create(
        db,
        request=CreateJob(
            operation=JobOperation.PDF_PROCESS,
            requested_by_id=requester.id,
            project_id=project_id,
            idempotency_key=durable_idempotency_key or f"pdf-reservation:{job_id}",
            payload={
                "content_sha256": content_sha256,
                "original_filename": original_filename,
                "input_size_bytes": input_size_bytes,
            },
            job_id=job_id,
        ),
    )
    reservation = UploadReservation(
        id=durable_job.id,
        quota_owner_id=owner_id,
        reserved_size_kb=reserved_size_kb,
        reserved_reference_count=reserved_reference_count,
        content_sha256=content_sha256,
        original_filename=original_filename,
    )
    reservation.job = durable_job
    db.add(reservation)
    db.flush()
    db.refresh(reservation)
    return reservation
