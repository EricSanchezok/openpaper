"""SQLAlchemy/outbox adapter for the public Jobs application ports."""

from __future__ import annotations

from uuid import UUID

from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.application.contracts import JobResponse
from app.modules.jobs.application.jobs import (
    EnqueueJobCommand,
    ReserveOperationCommand,
    ReservedOperation,
)
from app.modules.jobs.infrastructure.repository import (
    CreateJob,
    EnqueueJob,
    job_repository,
)
from app.shared.domain.enums import JobOperation, JobStatus
from app.shared.domain import JsonValue
from sqlalchemy.orm import Session


def job_response(job: object) -> JobResponse:
    from app.modules.jobs.infrastructure.models import DurableJob

    if not isinstance(job, DurableJob):
        raise TypeError("expected DurableJob")
    return JobResponse.model_validate(job, from_attributes=True)


class SqlAlchemyJobsGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_by_idempotency_key(self, *, key: str) -> JobResponse | None:
        job = job_repository.find_by_idempotency_key(
            self._db,
            idempotency_key=key,
        )
        return job_response(job) if job is not None else None

    def enqueue(self, *, command: EnqueueJobCommand) -> JobResponse:
        base_url = get_webhook_base_url().rstrip("/")
        job = job_repository.enqueue(
            self._db,
            request=EnqueueJob(
                operation=command.operation,
                requested_by_id=command.requested_by_id,
                project_id=command.project_id,
                document_id=command.document_id,
                idempotency_key=command.idempotency_key,
                payload=command.payload,
                task_name=command.task_name,
                queue=command.queue,
                task_kwargs={
                    "request": command.payload,
                    "webhook_url": (
                        f"{base_url}/internal/v1/jobs/{command.job_id}/complete"
                    ),
                    "claim_url": (
                        f"{base_url}/internal/v1/jobs/{command.job_id}/claim"
                    ),
                },
                job_id=command.job_id,
            ),
        )
        return job_response(job)

    def reserve(self, *, command: ReserveOperationCommand) -> ReservedOperation:
        existing = job_repository.find_by_idempotency_key(
            self._db,
            idempotency_key=command.idempotency_key,
        )
        if existing is not None:
            return ReservedOperation(
                job=job_response(existing),
                payload=existing.payload,
                created=False,
            )
        job = job_repository.create(
            self._db,
            request=CreateJob(
                job_id=command.operation_id,
                operation=command.operation,
                requested_by_id=command.requested_by_id,
                idempotency_key=command.idempotency_key,
                payload=command.payload,
            ),
        )
        return ReservedOperation(
            job=job_response(job),
            payload=job.payload,
            created=job.id == command.operation_id,
        )

    def complete(
        self,
        *,
        operation_id: UUID,
        result: dict[str, JsonValue],
    ) -> JobResponse:
        job, _changed = job_repository.complete(
            self._db,
            job_id=operation_id,
            result=result,
        )
        return job_response(job)

    def fail(self, *, operation_id: UUID, error_code: str) -> JobResponse:
        job, _changed = job_repository.fail(
            self._db,
            job_id=operation_id,
            error_code=error_code,
        )
        return job_response(job)

    def list(
        self,
        *,
        requested_by_id: int,
        project_id: UUID | None,
        document_id: UUID | None,
        operation: JobOperation | None,
        statuses: tuple[JobStatus, ...] | None,
    ) -> list[JobResponse]:
        return [
            job_response(job)
            for job in job_repository.list_for_requester(
                self._db,
                requested_by_id=requested_by_id,
                project_id=project_id,
                document_id=document_id,
                operation=operation,
                statuses=statuses,
            )
        ]

    def get(self, *, requested_by_id: int, job_id: UUID) -> JobResponse:
        return job_response(
            job_repository.require_for_requester(
                self._db,
                job_id=job_id,
                requested_by_id=requested_by_id,
            )
        )
