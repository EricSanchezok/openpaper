"""Operation-specific research handlers behind the generic job callback."""

from __future__ import annotations

import uuid

from app.database.models import (
    JobOperation,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
    ResearchItemKind,
    ResearchScopeType,
)
from app.shared.domain import AppError, FailureKind
from app.helpers.ai_limits import release_concurrency_by_id
from app.llm.token_credits import llm_usage_context, settle_token_usage
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.jobs.application.contracts import (
    AudioOverviewTaskPayload,
    AudioOverviewWebhookData,
    DataTableTaskPayload,
    DataTableWebhookData,
    JobClaimResponse,
    TokenUsageEventPayload,
)
from sqlalchemy.orm import Session


def settle_jobs_usage(user_id: int, events: list[TokenUsageEventPayload]) -> None:
    for event in events:
        with llm_usage_context(
            user_id=user_id,
            feature=event.feature,
            operation_id=event.operation_id,
        ):
            settle_token_usage(
                model=event.model,
                reasoning_level=event.reasoning_level,
                provider_request_id=event.provider_request_id,
                prompt_tokens=event.prompt_tokens,
                completion_tokens=event.completion_tokens,
                reasoning_tokens=event.reasoning_tokens,
                cache_hit_tokens=event.cache_hit_tokens,
                cache_miss_tokens=event.cache_miss_tokens,
                total_tokens=event.total_tokens,
                idempotency_key=event.idempotency_key,
                status=event.status,
            )


def _validate_callback(
    *,
    job_id: uuid.UUID,
    task_id: uuid.UUID,
    operation: str,
    expected_operation: JobOperation,
) -> None:
    if operation != expected_operation.value:
        raise AppError(
            code="job_operation_mismatch",
            message="Job operation does not match callback",
            kind=FailureKind.CONFLICT,
        )
    if task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback ID does not match",
            kind=FailureKind.CONFLICT,
        )


async def complete_audio_job(
    job_id: uuid.UUID,
    webhook: AudioOverviewWebhookData,
    db: Session,
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    _validate_callback(
        job_id=job_id,
        task_id=webhook.task_id,
        operation=job.operation,
        expected_operation=JobOperation.AUDIO_GENERATE,
    )
    if webhook.status == "failed":
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=webhook.error or "audio_generation_failed",
        )
    else:
        task_payload = AudioOverviewTaskPayload.model_validate(job.payload)
        result = webhook.result
        if result is None:
            raise RuntimeError("validated_audio_callback_without_result")
        if result.research_item_id != task_payload.research_item_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Research output ID does not match",
                kind=FailureKind.CONFLICT,
            )
        _, changed = job_repository.complete(
            db,
            job_id=job_id,
            result=result.model_dump(mode="json"),
        )
        if changed:
            scope_type = ResearchScopeType(task_payload.scope_type)
            item = ResearchItem(
                id=result.research_item_id,
                kind=ResearchItemKind.AUDIO_OVERVIEW.value,
                created_by_id=job.requested_by_id,
                scope_type=scope_type.value,
                document_id=(
                    task_payload.scope_id
                    if scope_type == ResearchScopeType.DOCUMENT
                    else None
                ),
                project_id=(
                    task_payload.scope_id
                    if scope_type == ResearchScopeType.PROJECT
                    else None
                ),
                is_shared=True,
                source_job_id=job_id,
            )
            item.audio_overview = ResearchAudioOverview(
                title=result.title,
                transcript=result.transcript,
                citations=result.citations,
                s3_object_key=result.s3_object_key,
                voice_id=result.voice_id,
                model_version=result.model_version,
            )
            db.add(item)
    if job.requested_by_id is not None:
        settle_jobs_usage(job.requested_by_id, webhook.usage_events)
        db.commit()
        await release_concurrency_by_id(
            user_id=job.requested_by_id,
            category="audio",
            operation_id=str(job_id),
        )
        await release_concurrency_by_id(
            user_id=job.requested_by_id,
            category="background",
            operation_id=str(job_id),
        )
    return JobClaimResponse(claimed=changed)


async def complete_data_table_job(
    job_id: uuid.UUID,
    webhook: DataTableWebhookData,
    db: Session,
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    _validate_callback(
        job_id=job_id,
        task_id=webhook.task_id,
        operation=job.operation,
        expected_operation=JobOperation.DATA_TABLE_GENERATE,
    )
    if webhook.status == "failed":
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=webhook.error or "data_table_processing_failed",
        )
    else:
        task_payload = DataTableTaskPayload.model_validate(job.payload)
        result = webhook.result
        if result is None:
            raise RuntimeError("validated_data_table_callback_without_result")
        if result.research_item_id != task_payload.research_item_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Research output ID does not match",
                kind=FailureKind.CONFLICT,
            )
        _, changed = job_repository.complete(
            db,
            job_id=job_id,
            result=result.model_dump(mode="json"),
        )
        if changed:
            item = ResearchItem(
                id=result.research_item_id,
                kind=ResearchItemKind.DATA_TABLE.value,
                created_by_id=job.requested_by_id,
                scope_type=ResearchScopeType.PROJECT.value,
                project_id=job.project_id,
                is_shared=True,
                source_job_id=job_id,
            )
            item.data_table = ResearchDataTable(
                title=result.title,
                columns=result.columns,
                rows=[row.model_dump(mode="json") for row in result.rows],
                citations=[
                    citation.model_dump(mode="json")
                    for row in result.rows
                    for cell in row.values.values()
                    for citation in cell.citations
                ],
                row_failures=[str(document_id) for document_id in result.row_failures],
            )
            db.add(item)
    if job.requested_by_id is not None:
        settle_jobs_usage(job.requested_by_id, webhook.usage_events)
        db.commit()
        await release_concurrency_by_id(
            user_id=job.requested_by_id,
            category="background",
            operation_id=str(job_id),
        )
    return JobClaimResponse(claimed=changed)
