"""Durable generation endpoints for typed research outputs."""

from __future__ import annotations

import uuid

from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.database import get_db
from app.database.models import JobOperation, JobStatus
from app.shared.domain import AppError
from app.modules.papers.infrastructure.access import require_document_access
from app.modules.projects.infrastructure.access import require_project_access
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.jobs.application.contracts import (
    CreateAudioOverviewRequest,
    CreateDataTableRequest,
    CreateJobResponse,
    JobListResponse,
    JobResponse,
)
from app.shared.application import Actor
from app.modules.research.infrastructure.generation import (
    enqueue_audio_generation,
    enqueue_data_table_generation,
    list_project_generation_documents,
)
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

document_generation_router = APIRouter()
project_generation_router = APIRouter()
jobs_router = APIRouter()


def _job_response(job: object) -> JobResponse:
    from app.database.models import DurableJob

    if not isinstance(job, DurableJob):
        raise TypeError("expected DurableJob")
    return JobResponse.model_validate(job, from_attributes=True)


@document_generation_router.post(
    "/{document_id}/audio-overviews",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_document_audio_overview(
    document_id: uuid.UUID,
    request: CreateAudioOverviewRequest,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CreateJobResponse:
    access = require_document_access(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    return await enqueue_audio_generation(
        db=db,
        user=current_user,
        ip_address=http_request.client.host if http_request.client else "unknown",
        scope_type="document",
        scope_id=document_id,
        documents=[access.document],
        request=request,
        idempotency_key=idempotency_key,
    )


@project_generation_router.post(
    "/{project_id}/audio-overviews",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_project_audio_overview(
    project_id: uuid.UUID,
    request: CreateAudioOverviewRequest,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CreateJobResponse:
    require_project_access(db, project_id=project_id, user_id=current_user.id)
    documents = list_project_generation_documents(db, project_id=project_id)
    if not documents:
        raise AppError(
            code="project_has_no_papers",
            message="Add at least one paper before generating audio",
            status_code=409,
        )
    return await enqueue_audio_generation(
        db=db,
        user=current_user,
        ip_address=http_request.client.host if http_request.client else "unknown",
        scope_type="project",
        scope_id=project_id,
        documents=documents,
        request=request,
        idempotency_key=idempotency_key,
    )


@jobs_router.get("", response_model=JobListResponse)
def list_jobs(
    project_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    operation: JobOperation | None = None,
    active: bool = False,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> JobListResponse:
    jobs = job_repository.list_for_requester(
        db,
        requested_by_id=current_user.id,
        project_id=project_id,
        document_id=document_id,
        operation=operation,
        statuses=(JobStatus.PENDING, JobStatus.RUNNING) if active else None,
    )
    return JobListResponse(items=[_job_response(job) for job in jobs])


@jobs_router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> JobResponse:
    job = job_repository.require_for_requester(
        db,
        job_id=job_id,
        requested_by_id=current_user.id,
    )
    return _job_response(job)


@project_generation_router.post(
    "/{project_id}/data-tables",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_project_data_table(
    project_id: uuid.UUID,
    request: CreateDataTableRequest,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CreateJobResponse:
    require_project_access(db, project_id=project_id, user_id=current_user.id)
    documents = list_project_generation_documents(db, project_id=project_id)
    if not documents:
        raise AppError(
            code="project_has_no_papers",
            message="Add at least one paper before generating a data table",
            status_code=409,
        )

    return await enqueue_data_table_generation(
        db=db,
        user=current_user,
        ip_address=http_request.client.host if http_request.client else "unknown",
        project_id=project_id,
        documents=documents,
        request=request,
        idempotency_key=idempotency_key,
    )
