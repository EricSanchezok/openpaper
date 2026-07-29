"""HTTP adapters for durable Research generation and Jobs queries."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_jobs, build_research_generation
from app.database.database import get_db
from app.modules.jobs.application.contracts import (
    CreateAudioOverviewRequest,
    CreateDataTableRequest,
    CreateJobResponse,
    JobListResponse,
    JobResponse,
)
from app.shared.application import Actor
from app.shared.domain.enums import JobOperation
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy.orm import Session

document_generation_router = APIRouter()
project_generation_router = APIRouter()
jobs_router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@document_generation_router.post(
    "/{document_id}/audio-overviews",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_document_audio_overview(
    document_id: UUID,
    request: CreateAudioOverviewRequest,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CreateJobResponse:
    return await build_research_generation(db=db).document_audio(
        actor=current_user,
        client_ip=_client_ip(http_request),
        document_id=document_id,
        request=request,
        idempotency_key=idempotency_key,
    )


@project_generation_router.post(
    "/{project_id}/audio-overviews",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_project_audio_overview(
    project_id: UUID,
    request: CreateAudioOverviewRequest,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CreateJobResponse:
    return await build_research_generation(db=db).project_audio(
        actor=current_user,
        client_ip=_client_ip(http_request),
        project_id=project_id,
        request=request,
        idempotency_key=idempotency_key,
    )


@jobs_router.get("", response_model=JobListResponse)
def list_jobs(
    project_id: UUID | None = None,
    document_id: UUID | None = None,
    operation: JobOperation | None = None,
    active: bool = False,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> JobListResponse:
    return build_jobs(db=db).list(
        actor=current_user,
        project_id=project_id,
        document_id=document_id,
        operation=operation,
        active=active,
    )


@jobs_router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> JobResponse:
    return build_jobs(db=db).get(actor=current_user, job_id=job_id)


@project_generation_router.post(
    "/{project_id}/data-tables",
    response_model=CreateJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_project_data_table(
    project_id: UUID,
    request: CreateDataTableRequest,
    http_request: Request,
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CreateJobResponse:
    return await build_research_generation(db=db).project_data_table(
        actor=current_user,
        client_ip=_client_ip(http_request),
        project_id=project_id,
        request=request,
        idempotency_key=idempotency_key,
    )
