"""Generic durable-job lifecycle and terminal callback use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.jobs.application.contracts import (
    JobClaimResponse,
    JobFailureCallback,
)
from app.shared.domain import AppError
from app.shared.domain.enums import JobOperation
from pydantic import BaseModel, ValidationError


class JobLifecyclePort(Protocol):
    def operation(self, *, job_id: UUID) -> JobOperation: ...

    def claim(self, *, job_id: UUID) -> bool: ...

    def heartbeat(self, *, job_id: UUID) -> bool: ...

    def fail(self, *, job_id: UUID, error_code: str) -> bool: ...


class JobCompletionHandler(Protocol):
    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object: ...


class ScheduledJobPort(Protocol):
    def schedule_zotero_sync(self, *, threshold_seconds: int) -> dict[str, int]: ...


@dataclass(frozen=True, slots=True)
class RegisteredJobCallback:
    contract: type[BaseModel]
    handler: JobCompletionHandler


class JobCallbacks:
    """Operation registry used by the single generic callback surface."""

    def __init__(
        self,
        *,
        lifecycle: JobLifecyclePort,
        handlers: dict[JobOperation, RegisteredJobCallback],
        schedules: ScheduledJobPort,
    ) -> None:
        self._lifecycle = lifecycle
        self._handlers = handlers
        self._schedules = schedules

    def claim(self, *, job_id: UUID) -> JobClaimResponse:
        return JobClaimResponse(claimed=self._lifecycle.claim(job_id=job_id))

    def heartbeat(self, *, job_id: UUID) -> JobClaimResponse:
        return JobClaimResponse(claimed=self._lifecycle.heartbeat(job_id=job_id))

    async def complete(self, *, job_id: UUID, payload: dict[str, object]) -> object:
        operation = self._lifecycle.operation(job_id=job_id)
        registration = self._handlers.get(operation)
        if registration is None:
            raise AppError(
                code="job_operation_unsupported",
                message="Job operation has no callback handler",
                status_code=409,
            )
        try:
            callback = registration.contract.model_validate(payload)
        except ValidationError as exc:
            raise AppError(
                code="job_callback_invalid",
                message="Job callback payload is invalid for its operation",
                status_code=422,
            ) from exc
        return await registration.handler.complete(job_id=job_id, callback=callback)

    def fail(self, *, job_id: UUID, callback: JobFailureCallback) -> JobClaimResponse:
        if callback.task_id != job_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Job callback ID does not match",
                status_code=409,
            )
        return JobClaimResponse(
            claimed=self._lifecycle.fail(job_id=job_id, error_code=callback.error_code)
        )

    def schedule_zotero_sync(self, *, threshold_seconds: int) -> dict[str, int]:
        if threshold_seconds < 60:
            raise AppError(
                code="zotero_sync_interval_invalid",
                message="Zotero sync interval is invalid",
                status_code=422,
            )
        return self._schedules.schedule_zotero_sync(threshold_seconds=threshold_seconds)
