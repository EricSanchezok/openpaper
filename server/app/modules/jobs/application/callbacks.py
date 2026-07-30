"""Generic durable-job lifecycle and terminal callback use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
    TokenUsageEventPayload,
)
from app.modules.jobs.application.actions import (
    JOB_COMPLETED,
    JOB_CREATED,
    JOB_FAILED,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import JsonValue
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobOperation, JobStatus
from pydantic import BaseModel, ValidationError


class JobLifecyclePort(Protocol):
    def operation(self, *, job_id: UUID) -> JobOperation: ...

    def status(self, *, job_id: UUID) -> JobStatus: ...

    def claim(self, *, job_id: UUID) -> bool: ...

    def heartbeat(self, *, job_id: UUID) -> bool: ...

    def fail(self, *, job_id: UUID, error_code: str) -> bool: ...


class JobCompletionHandler(Protocol):
    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult: ...


@dataclass(frozen=True, slots=True)
class PdfPostprocessResolution:
    doi: str | None = None
    journal: str | None = None
    publisher: str | None = None
    publish_date: str | None = None
    field_provenance: dict[str, JsonValue] | None = None


@runtime_checkable
class PdfPostprocessCompletionHandler(Protocol):
    async def complete_resolved(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
        resolution: PdfPostprocessResolution,
    ) -> JobHandlerResult: ...


class ScheduledJobPort(Protocol):
    def schedule_zotero_sync(
        self,
        *,
        threshold_seconds: int,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> ScheduledZoteroJobs: ...


@dataclass(frozen=True, slots=True)
class ScheduledZoteroJobs:
    total_users: int
    scheduled_jobs: int
    skipped_users: int
    created_job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class RegisteredJobCallback:
    contract: type[BaseModel]
    handler: JobCompletionHandler


@dataclass(frozen=True, slots=True)
class ReleaseJobConcurrency:
    user_id: int
    category: Literal["audio", "background"]
    job_id: UUID


@dataclass(frozen=True, slots=True)
class SettleJobUsage:
    user_id: int
    events: tuple[TokenUsageEventPayload, ...]


@dataclass(frozen=True, slots=True)
class RecordJobTelemetry:
    actor_id: int
    event: str
    properties: tuple[tuple[str, JsonValue], ...]


type JobPostCommitAction = ReleaseJobConcurrency | SettleJobUsage | RecordJobTelemetry


@dataclass(frozen=True, slots=True)
class JobHandlerResult:
    value: object
    changes: tuple[OperationChange, ...] = ()
    post_commit: tuple[JobPostCommitAction, ...] = ()


@dataclass(frozen=True, slots=True)
class JobCompletionResult:
    value: object
    post_commit: tuple[JobPostCommitAction, ...] = ()


class JobCallbacks:
    """Operation registry used by the single generic callback surface."""

    def __init__(
        self,
        *,
        lifecycle: JobLifecyclePort,
        handlers: dict[JobOperation, RegisteredJobCallback],
        schedules: ScheduledJobPort,
        journal: OperationJournal,
    ) -> None:
        self._lifecycle = lifecycle
        self._handlers = handlers
        self._schedules = schedules
        self._journal = journal

    def claim(self, *, job_id: UUID) -> JobClaimResponse:
        return JobClaimResponse(claimed=self._lifecycle.claim(job_id=job_id))

    def heartbeat(self, *, job_id: UUID) -> JobClaimResponse:
        return JobClaimResponse(claimed=self._lifecycle.heartbeat(job_id=job_id))

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        payload: dict[str, object],
    ) -> JobCompletionResult:
        job_operation = self._lifecycle.operation(job_id=job_id)
        registration = self._registration(job_operation)
        callback = self._validate_callback(registration, payload)
        before = self._lifecycle.status(job_id=job_id)
        handler_result = await registration.handler.complete(
            actor=actor,
            operation=operation,
            job_id=job_id,
            callback=callback,
        )
        return self._record_completion(
            actor=actor,
            operation=operation,
            job_id=job_id,
            before=before,
            handler_result=handler_result,
        )

    async def complete_pdf_postprocess(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        payload: dict[str, object],
        resolution: PdfPostprocessResolution,
    ) -> JobCompletionResult:
        job_operation = self._lifecycle.operation(job_id=job_id)
        if job_operation is not JobOperation.PDF_POSTPROCESS:
            raise AppError(
                code="job_operation_mismatch",
                message="Job operation does not match callback",
                kind=FailureKind.CONFLICT,
            )
        registration = self._registration(job_operation)
        callback = self._validate_callback(registration, payload)
        handler = registration.handler
        if not isinstance(handler, PdfPostprocessCompletionHandler):
            raise RuntimeError("pdf_postprocess_handler_contract_invalid")
        before = self._lifecycle.status(job_id=job_id)
        handler_result = await handler.complete_resolved(
            actor=actor,
            operation=operation,
            job_id=job_id,
            callback=callback,
            resolution=resolution,
        )
        return self._record_completion(
            actor=actor,
            operation=operation,
            job_id=job_id,
            before=before,
            handler_result=handler_result,
        )

    def _registration(
        self,
        operation: JobOperation,
    ) -> RegisteredJobCallback:
        registration = self._handlers.get(operation)
        if registration is None:
            raise AppError(
                code="job_operation_unsupported",
                message="Job operation has no callback handler",
                kind=FailureKind.CONFLICT,
            )
        return registration

    @staticmethod
    def _validate_callback(
        registration: RegisteredJobCallback,
        payload: dict[str, object],
    ) -> BaseModel:
        try:
            return registration.contract.model_validate(payload)
        except ValidationError as exc:
            raise AppError(
                code="job_callback_invalid",
                message="Job callback payload is invalid for its operation",
                kind=FailureKind.UNPROCESSABLE,
            ) from exc

    def _record_completion(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        before: JobStatus,
        handler_result: JobHandlerResult,
    ) -> JobCompletionResult:
        after = self._lifecycle.status(job_id=job_id)
        changes = list(handler_result.changes)
        terminal_action = _terminal_action(before=before, after=after)
        if terminal_action is not None:
            changes.append(
                OperationChange(
                    action=terminal_action,
                    resources=(ResourceRef("job", str(job_id)),),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )
        return JobCompletionResult(
            value=handler_result.value,
            post_commit=handler_result.post_commit,
        )

    def fail(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: JobFailureCallback,
    ) -> JobClaimResponse:
        if callback.task_id != job_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Job callback ID does not match",
                kind=FailureKind.CONFLICT,
            )
        changed = self._lifecycle.fail(
            job_id=job_id,
            error_code=callback.error_code,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_FAILED,
                resources=(ResourceRef("job", str(job_id)),),
            )
        return JobClaimResponse(claimed=changed)

    def schedule_zotero_sync(
        self,
        *,
        operation: OperationContext,
        threshold_seconds: int,
    ) -> dict[str, int]:
        if threshold_seconds < 60:
            raise AppError(
                code="zotero_sync_interval_invalid",
                message="Zotero sync interval is invalid",
                kind=FailureKind.UNPROCESSABLE,
            )
        scheduled = self._schedules.schedule_zotero_sync(
            threshold_seconds=threshold_seconds,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
        )
        self._journal.append_many(
            actor=None,
            operation=operation,
            changes=(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(ResourceRef("job", str(job_id)),),
                )
                for job_id in scheduled.created_job_ids
            ),
        )
        return {
            "total_users": scheduled.total_users,
            "scheduled_jobs": scheduled.scheduled_jobs,
            "skipped_users": scheduled.skipped_users,
        }


def _terminal_action(
    *,
    before: JobStatus,
    after: JobStatus,
) -> OperationAction | None:
    if before in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
        return None
    if after is JobStatus.COMPLETED:
        return JOB_COMPLETED
    if after in {JobStatus.FAILED, JobStatus.CANCELLED}:
        return JOB_FAILED
    return None


__all__ = [
    "JobCallbacks",
    "JobCompletionHandler",
    "JobCompletionResult",
    "JobHandlerResult",
    "JobPostCommitAction",
    "PdfPostprocessCompletionHandler",
    "PdfPostprocessResolution",
    "RecordJobTelemetry",
    "RegisteredJobCallback",
    "ReleaseJobConcurrency",
    "ScheduledZoteroJobs",
    "SettleJobUsage",
]
