"""Durable generation endpoints for typed research outputs."""

from __future__ import annotations

import uuid
from typing import Literal

from app.auth.dependencies import get_required_user
from app.database.database import get_db
from app.database.models import Document, JobOperation, ProjectPaper
from app.database.models.base import JsonValue
from app.errors import AppError
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency_by_id,
)
from app.helpers.celery_config import get_webhook_base_url
from app.llm.token_credits import has_token_credits
from app.policies.documents import require_document_access
from app.policies.projects import require_project_access
from app.repositories.jobs import EnqueueJob, job_repository
from app.schemas.jobs import (
    AudioOverviewTaskPayload,
    AudioSourceDocumentPayload,
    JobResponse,
    DataTableSourceDocumentPayload,
    DataTableTaskPayload,
    DataTableTaskTablePayload,
)
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

document_generation_router = APIRouter()
project_generation_router = APIRouter()
jobs_router = APIRouter()
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class CreateAudioOverviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    additional_instructions: str | None = Field(default=None, max_length=10_000)
    length: Literal["short", "medium", "long"] = "medium"


class CreateJobResponse(BaseModel):
    job: JobResponse


class CreateDataTableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=240)
    columns: list[str] = Field(min_length=1, max_length=50)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, columns: list[str]) -> list[str]:
        normalized = [column.strip() for column in columns]
        if any(not column or len(column) > 200 for column in normalized):
            raise ValueError("columns must contain between 1 and 200 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("columns must be unique")
        return normalized


def _job_response(job: object) -> JobResponse:
    from app.database.models import DurableJob

    if not isinstance(job, DurableJob):
        raise TypeError("expected DurableJob")
    return JobResponse.model_validate(job, from_attributes=True)


def _source(document: Document) -> AudioSourceDocumentPayload:
    if not document.parser_markdown_s3_key:
        raise AppError(
            code="document_not_ready",
            message="The document has not finished indexing",
            status_code=409,
        )
    return AudioSourceDocumentPayload(
        id=document.id,
        title=document.title or document.original_filename,
        canonical_s3_key=document.parser_markdown_s3_key,
    )


async def _enqueue_audio(
    *,
    db: Session,
    current_user: CurrentUser,
    http_request: Request,
    scope_type: Literal["document", "project"],
    scope_id: uuid.UUID,
    documents: list[Document],
    request: CreateAudioOverviewRequest,
    idempotency_key: str | None,
) -> CreateJobResponse:
    if not has_token_credits(db, user=current_user):
        raise AppError(
            code="token_quota_exceeded",
            message="Token Credits are exhausted",
            status_code=429,
        )
    try:
        await enforce_rate_limit(
            user_id=current_user.id,
            ip_address=(http_request.client.host if http_request.client else "unknown"),
            feature="audio",
        )
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code, message="AI request limit exceeded", status_code=429
        )

    job_id = uuid.uuid4()
    try:
        await acquire_concurrency(
            user_id=current_user.id,
            category="background",
            operation_id=str(job_id),
        )
        try:
            await acquire_concurrency(
                user_id=current_user.id,
                category="audio",
                operation_id=str(job_id),
            )
        except Exception:
            await release_concurrency_by_id(
                user_id=current_user.id,
                category="background",
                operation_id=str(job_id),
            )
            raise
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code, message="AI request limit exceeded", status_code=429
        )

    research_item_id = uuid.uuid4()
    payload_model = AudioOverviewTaskPayload(
        research_item_id=research_item_id,
        scope_type=scope_type,
        scope_id=scope_id,
        documents=[_source(document) for document in documents],
        length=request.length,
        additional_instructions=request.additional_instructions,
    )
    payload = _JSON_OBJECT.validate_python(payload_model.model_dump(mode="json"))
    base_url = get_webhook_base_url().rstrip("/")
    operation_key = (
        f"audio:{current_user.id}:{scope_type}:{scope_id}:{idempotency_key}"
        if idempotency_key
        else f"audio:{job_id}"
    )
    try:
        job = job_repository.enqueue(
            db,
            request=EnqueueJob(
                operation=JobOperation.AUDIO_GENERATE,
                requested_by_id=current_user.id,
                project_id=scope_id if scope_type == "project" else None,
                document_id=scope_id if scope_type == "document" else None,
                idempotency_key=operation_key,
                payload=payload,
                task_name="generate_audio_overview",
                queue="audio",
                task_kwargs={
                    "request": payload,
                    "webhook_url": f"{base_url}/api/webhooks/jobs/{job_id}/audio",
                    "claim_url": f"{base_url}/api/webhooks/jobs/{job_id}/claim",
                },
                job_id=job_id,
            ),
        )
        db.commit()
        db.refresh(job)
        if job.id != job_id:
            await release_concurrency_by_id(
                user_id=current_user.id,
                category="audio",
                operation_id=str(job_id),
            )
            await release_concurrency_by_id(
                user_id=current_user.id,
                category="background",
                operation_id=str(job_id),
            )
    except Exception:
        db.rollback()
        await release_concurrency_by_id(
            user_id=current_user.id,
            category="audio",
            operation_id=str(job_id),
        )
        await release_concurrency_by_id(
            user_id=current_user.id,
            category="background",
            operation_id=str(job_id),
        )
        raise
    return CreateJobResponse(job=_job_response(job))


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
    current_user: CurrentUser = Depends(get_required_user),
) -> CreateJobResponse:
    access = require_document_access(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    return await _enqueue_audio(
        db=db,
        current_user=current_user,
        http_request=http_request,
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
    current_user: CurrentUser = Depends(get_required_user),
) -> CreateJobResponse:
    require_project_access(db, project_id=project_id, user_id=current_user.id)
    documents = list(
        db.scalars(
            select(Document)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(ProjectPaper.project_id == project_id)
            .order_by(ProjectPaper.created_at)
        ).all()
    )
    if not documents:
        raise AppError(
            code="project_has_no_papers",
            message="Add at least one paper before generating audio",
            status_code=409,
        )
    return await _enqueue_audio(
        db=db,
        current_user=current_user,
        http_request=http_request,
        scope_type="project",
        scope_id=project_id,
        documents=documents,
        request=request,
        idempotency_key=idempotency_key,
    )


@jobs_router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JobResponse:
    job = job_repository.require(db, job_id=job_id)
    if job.requested_by_id != current_user.id:
        raise AppError(code="job_not_found", message="Job not found", status_code=404)
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
    current_user: CurrentUser = Depends(get_required_user),
) -> CreateJobResponse:
    require_project_access(db, project_id=project_id, user_id=current_user.id)
    if not has_token_credits(db, user=current_user):
        raise AppError(
            code="token_quota_exceeded",
            message="Token Credits are exhausted",
            status_code=429,
        )
    try:
        await enforce_rate_limit(
            user_id=current_user.id,
            ip_address=(http_request.client.host if http_request.client else "unknown"),
            feature="data_table",
        )
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code, message="AI request limit exceeded", status_code=429
        )

    documents = list(
        db.scalars(
            select(Document)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(ProjectPaper.project_id == project_id)
            .order_by(ProjectPaper.created_at)
        ).all()
    )
    if not documents:
        raise AppError(
            code="project_has_no_papers",
            message="Add at least one paper before generating a data table",
            status_code=409,
        )

    job_id = uuid.uuid4()
    try:
        await acquire_concurrency(
            user_id=current_user.id,
            category="background",
            operation_id=str(job_id),
        )
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code, message="AI request limit exceeded", status_code=429
        )

    research_item_id = uuid.uuid4()
    payload_model = DataTableTaskPayload(
        research_item_id=research_item_id,
        title=request.title,
        table=DataTableTaskTablePayload(
            columns=request.columns,
            papers=[
                DataTableSourceDocumentPayload(
                    id=document.id,
                    title=document.title or document.original_filename,
                    raw_content=document.raw_content or "",
                )
                for document in documents
            ],
        ),
    )
    payload = _JSON_OBJECT.validate_python(payload_model.model_dump(mode="json"))
    base_url = get_webhook_base_url().rstrip("/")
    operation_key = (
        f"data-table:{current_user.id}:{project_id}:{idempotency_key}"
        if idempotency_key
        else f"data-table:{job_id}"
    )
    try:
        job = job_repository.enqueue(
            db,
            request=EnqueueJob(
                operation=JobOperation.DATA_TABLE_GENERATE,
                requested_by_id=current_user.id,
                project_id=project_id,
                idempotency_key=operation_key,
                payload=payload,
                task_name="process_data_table",
                queue="data_table",
                task_kwargs={
                    "request": payload,
                    "webhook_url": (
                        f"{base_url}/api/webhooks/jobs/{job_id}/data-table"
                    ),
                    "claim_url": f"{base_url}/api/webhooks/jobs/{job_id}/claim",
                },
                job_id=job_id,
            ),
        )
        db.commit()
        db.refresh(job)
        if job.id != job_id:
            await release_concurrency_by_id(
                user_id=current_user.id,
                category="background",
                operation_id=str(job_id),
            )
    except Exception:
        db.rollback()
        await release_concurrency_by_id(
            user_id=current_user.id,
            category="background",
            operation_id=str(job_id),
        )
        raise
    return CreateJobResponse(job=_job_response(job))
