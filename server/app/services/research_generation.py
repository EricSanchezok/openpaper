"""Durable AI research generation with quota and concurrency settlement."""

from __future__ import annotations

import uuid
from typing import Literal

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
from app.repositories.jobs import EnqueueJob, job_repository
from app.schemas.jobs import (
    AudioOverviewTaskPayload,
    AudioSourceDocumentPayload,
    CreateAudioOverviewRequest,
    CreateDataTableRequest,
    CreateJobResponse,
    DataTableSourceDocumentPayload,
    DataTableTaskPayload,
    DataTableTaskTablePayload,
    JobResponse,
)
from app.schemas.user import CurrentUser
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


def _job_response(job: object) -> JobResponse:
    from app.database.models import DurableJob

    if not isinstance(job, DurableJob):
        raise TypeError("expected DurableJob")
    return JobResponse.model_validate(job, from_attributes=True)


def _audio_source(document: Document) -> AudioSourceDocumentPayload:
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


def list_project_generation_documents(
    db: Session,
    *,
    project_id: uuid.UUID,
) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(ProjectPaper.project_id == project_id)
            .order_by(ProjectPaper.created_at)
        ).all()
    )


def _require_token_credits(db: Session, *, user: CurrentUser) -> None:
    if not has_token_credits(db, user=user):
        raise AppError(
            code="token_quota_exceeded",
            message="Token Credits are exhausted",
            status_code=429,
        )


async def _enforce_ai_rate_limit(
    *,
    user_id: int,
    ip_address: str,
    feature: Literal["audio", "data_table"],
) -> None:
    try:
        await enforce_rate_limit(
            user_id=user_id,
            ip_address=ip_address,
            feature=feature,
        )
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code,
            message="AI request limit exceeded",
            status_code=429,
        ) from None


async def _acquire_audio_capacity(*, user_id: int, job_id: uuid.UUID) -> None:
    try:
        await acquire_concurrency(
            user_id=user_id,
            category="background",
            operation_id=str(job_id),
        )
        try:
            await acquire_concurrency(
                user_id=user_id,
                category="audio",
                operation_id=str(job_id),
            )
        except Exception:
            await release_concurrency_by_id(
                user_id=user_id,
                category="background",
                operation_id=str(job_id),
            )
            raise
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code,
            message="AI request limit exceeded",
            status_code=429,
        ) from None


async def enqueue_audio_generation(
    *,
    db: Session,
    user: CurrentUser,
    ip_address: str,
    scope_type: Literal["document", "project"],
    scope_id: uuid.UUID,
    documents: list[Document],
    request: CreateAudioOverviewRequest,
    idempotency_key: str | None,
) -> CreateJobResponse:
    _require_token_credits(db, user=user)
    await _enforce_ai_rate_limit(
        user_id=user.id,
        ip_address=ip_address,
        feature="audio",
    )
    job_id = uuid.uuid4()
    await _acquire_audio_capacity(user_id=user.id, job_id=job_id)

    research_item_id = uuid.uuid4()
    payload_model = AudioOverviewTaskPayload(
        research_item_id=research_item_id,
        scope_type=scope_type,
        scope_id=scope_id,
        documents=[_audio_source(document) for document in documents],
        length=request.length,
        additional_instructions=request.additional_instructions,
    )
    payload = _JSON_OBJECT.validate_python(payload_model.model_dump(mode="json"))
    base_url = get_webhook_base_url().rstrip("/")
    operation_key = (
        f"audio:{user.id}:{scope_type}:{scope_id}:{idempotency_key}"
        if idempotency_key
        else f"audio:{job_id}"
    )
    try:
        job = job_repository.enqueue(
            db,
            request=EnqueueJob(
                operation=JobOperation.AUDIO_GENERATE,
                requested_by_id=user.id,
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
                user_id=user.id,
                category="audio",
                operation_id=str(job_id),
            )
            await release_concurrency_by_id(
                user_id=user.id,
                category="background",
                operation_id=str(job_id),
            )
    except Exception:
        db.rollback()
        await release_concurrency_by_id(
            user_id=user.id,
            category="audio",
            operation_id=str(job_id),
        )
        await release_concurrency_by_id(
            user_id=user.id,
            category="background",
            operation_id=str(job_id),
        )
        raise
    return CreateJobResponse(job=_job_response(job))


async def enqueue_data_table_generation(
    *,
    db: Session,
    user: CurrentUser,
    ip_address: str,
    project_id: uuid.UUID,
    documents: list[Document],
    request: CreateDataTableRequest,
    idempotency_key: str | None,
) -> CreateJobResponse:
    _require_token_credits(db, user=user)
    await _enforce_ai_rate_limit(
        user_id=user.id,
        ip_address=ip_address,
        feature="data_table",
    )
    job_id = uuid.uuid4()
    try:
        await acquire_concurrency(
            user_id=user.id,
            category="background",
            operation_id=str(job_id),
        )
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code,
            message="AI request limit exceeded",
            status_code=429,
        ) from None

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
        f"data-table:{user.id}:{project_id}:{idempotency_key}"
        if idempotency_key
        else f"data-table:{job_id}"
    )
    try:
        job = job_repository.enqueue(
            db,
            request=EnqueueJob(
                operation=JobOperation.DATA_TABLE_GENERATE,
                requested_by_id=user.id,
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
                user_id=user.id,
                category="background",
                operation_id=str(job_id),
            )
    except Exception:
        db.rollback()
        await release_concurrency_by_id(
            user_id=user.id,
            category="background",
            operation_id=str(job_id),
        )
        raise
    return CreateJobResponse(job=_job_response(job))
