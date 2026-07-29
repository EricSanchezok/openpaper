"""Public Jobs application facade and durable enqueue port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.jobs.application.contracts import (
    JobListResponse,
    JobResponse,
)
from app.shared.application import Actor
from app.shared.domain import JsonValue
from app.shared.domain.enums import JobOperation, JobStatus


@dataclass(frozen=True, slots=True)
class EnqueueJobCommand:
    job_id: UUID
    operation: JobOperation
    requested_by_id: int
    idempotency_key: str
    payload: dict[str, JsonValue]
    task_name: str
    queue: str
    project_id: UUID | None = None
    document_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ReserveOperationCommand:
    operation_id: UUID
    operation: JobOperation
    requested_by_id: int
    idempotency_key: str
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ReservedOperation:
    job: JobResponse
    payload: dict[str, JsonValue]
    created: bool


class JobCommandPort(Protocol):
    def find_by_idempotency_key(self, *, key: str) -> JobResponse | None: ...

    def enqueue(self, *, command: EnqueueJobCommand) -> JobResponse: ...


class IdempotentOperationPort(Protocol):
    def reserve(self, *, command: ReserveOperationCommand) -> ReservedOperation: ...

    def complete(
        self,
        *,
        operation_id: UUID,
        result: dict[str, JsonValue],
    ) -> JobResponse: ...

    def fail(self, *, operation_id: UUID, error_code: str) -> JobResponse: ...


class JobQueryPort(Protocol):
    def list(
        self,
        *,
        requested_by_id: int,
        project_id: UUID | None,
        document_id: UUID | None,
        operation: JobOperation | None,
        statuses: tuple[JobStatus, ...] | None,
    ) -> list[JobResponse]: ...

    def get(self, *, requested_by_id: int, job_id: UUID) -> JobResponse: ...


class Jobs:
    def __init__(self, queries: JobQueryPort) -> None:
        self._queries = queries

    def list(
        self,
        *,
        actor: Actor,
        project_id: UUID | None,
        document_id: UUID | None,
        operation: JobOperation | None,
        active: bool,
    ) -> JobListResponse:
        statuses = (JobStatus.PENDING, JobStatus.RUNNING) if active else None
        return JobListResponse(
            items=self._queries.list(
                requested_by_id=actor.id,
                project_id=project_id,
                document_id=document_id,
                operation=operation,
                statuses=statuses,
            )
        )

    def get(self, *, actor: Actor, job_id: UUID) -> JobResponse:
        return self._queries.get(requested_by_id=actor.id, job_id=job_id)
