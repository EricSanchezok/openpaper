"""Transactional persistence for durable background operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.database.models import (
    DurableJob,
    JobDispatch,
    JobDispatchStatus,
    JobOperation,
    JobStatus,
)
from app.shared.domain import JsonValue
from app.errors import AppError
from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

DEFAULT_JOB_LEASE = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class CreateJob:
    operation: JobOperation
    requested_by_id: int | None
    idempotency_key: str
    payload: dict[str, JsonValue]
    job_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class EnqueueJob(CreateJob):
    task_name: str = ""
    queue: str = ""
    task_kwargs: dict[str, JsonValue] = field(default_factory=dict)
    available_at: datetime | None = None


class JobRepository:
    @staticmethod
    def list_for_requester(
        db: Session,
        *,
        requested_by_id: int,
        project_id: uuid.UUID | None = None,
        document_id: uuid.UUID | None = None,
        operation: JobOperation | None = None,
        statuses: tuple[JobStatus, ...] | None = None,
        limit: int = 100,
    ) -> list[DurableJob]:
        statement = select(DurableJob).where(
            DurableJob.requested_by_id == requested_by_id
        )
        if project_id is not None:
            statement = statement.where(DurableJob.project_id == project_id)
        if document_id is not None:
            statement = statement.where(DurableJob.document_id == document_id)
        if operation is not None:
            statement = statement.where(DurableJob.operation == operation.value)
        if statuses is not None:
            statement = statement.where(
                DurableJob.status.in_(status.value for status in statuses)
            )
        return list(
            db.scalars(
                statement.order_by(
                    DurableJob.created_at.desc(), DurableJob.id.desc()
                ).limit(limit)
            ).all()
        )

    def create(self, db: Session, *, request: CreateJob) -> DurableJob:
        job_id = request.job_id or uuid.uuid4()
        inserted_id = db.scalar(
            insert(DurableJob)
            .values(
                id=job_id,
                operation=request.operation.value,
                requested_by_id=request.requested_by_id,
                project_id=request.project_id,
                document_id=request.document_id,
                idempotency_key=request.idempotency_key,
                status=JobStatus.PENDING.value,
                payload=request.payload,
            )
            .on_conflict_do_nothing(index_elements=[DurableJob.idempotency_key])
            .returning(DurableJob.id)
        )
        if inserted_id is None:
            existing = db.scalar(
                select(DurableJob).where(
                    DurableJob.idempotency_key == request.idempotency_key
                )
            )
            if existing is None:
                raise RuntimeError("job_idempotency_lookup_failed")
            return existing

        job = db.get(DurableJob, inserted_id)
        if job is None:
            raise RuntimeError("inserted_job_not_found")
        return job

    @staticmethod
    def add_dispatch(
        db: Session,
        *,
        job: DurableJob,
        task_name: str,
        queue: str,
        kwargs: dict[str, JsonValue],
        available_at: datetime | None = None,
    ) -> JobDispatch:
        dispatch = JobDispatch(
            job_id=job.id,
            task_name=task_name,
            queue=queue,
            kwargs=kwargs,
            available_at=available_at or datetime.now(UTC),
        )
        db.add(dispatch)
        db.flush()
        return dispatch

    def enqueue(self, db: Session, *, request: EnqueueJob) -> DurableJob:
        job = self.create(db, request=request)
        if job.dispatch is None:
            self.add_dispatch(
                db,
                job=job,
                task_name=request.task_name,
                queue=request.queue,
                kwargs=request.task_kwargs,
                available_at=request.available_at,
            )
        return job

    @staticmethod
    def require(db: Session, *, job_id: uuid.UUID) -> DurableJob:
        job = db.get(DurableJob, job_id)
        if job is None:
            raise AppError(
                code="job_not_found",
                message="Job not found",
                status_code=404,
            )
        return job

    @staticmethod
    def require_for_requester(
        db: Session,
        *,
        job_id: uuid.UUID,
        requested_by_id: int,
    ) -> DurableJob:
        job = db.scalar(
            select(DurableJob).where(
                DurableJob.id == job_id,
                DurableJob.requested_by_id == requested_by_id,
            )
        )
        if job is None:
            raise AppError(
                code="job_not_found",
                message="Job not found",
                status_code=404,
            )
        return job

    @staticmethod
    def claim(
        db: Session,
        *,
        job_id: uuid.UUID,
        lease: timedelta = DEFAULT_JOB_LEASE,
    ) -> DurableJob | None:
        now = datetime.now(UTC)
        claimed = db.scalar(
            update(DurableJob)
            .where(
                DurableJob.id == job_id,
                or_(
                    DurableJob.status == JobStatus.PENDING.value,
                    (
                        (DurableJob.status == JobStatus.RUNNING.value)
                        & (DurableJob.lease_expires_at < now)
                    ),
                ),
            )
            .values(
                status=JobStatus.RUNNING.value,
                started_at=func.coalesce(DurableJob.started_at, now),
                lease_expires_at=now + lease,
                attempt_count=DurableJob.attempt_count + 1,
            )
            .returning(DurableJob)
        )
        db.commit()
        return claimed

    @staticmethod
    def heartbeat(
        db: Session,
        *,
        job_id: uuid.UUID,
        lease: timedelta = DEFAULT_JOB_LEASE,
    ) -> bool:
        return bool(
            db.execute(
                update(DurableJob)
                .where(
                    DurableJob.id == job_id,
                    DurableJob.status == JobStatus.RUNNING.value,
                )
                .values(lease_expires_at=datetime.now(UTC) + lease)
            ).rowcount
        )

    @staticmethod
    def recover_expired_leases(db: Session, *, limit: int) -> int:
        """Return abandoned jobs to the outbox without creating a second job."""
        now = datetime.now(UTC)
        expired_jobs = list(
            db.scalars(
                select(DurableJob)
                .where(
                    DurableJob.status == JobStatus.RUNNING.value,
                    DurableJob.lease_expires_at.is_not(None),
                    DurableJob.lease_expires_at < now,
                )
                .order_by(DurableJob.lease_expires_at, DurableJob.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for job in expired_jobs:
            job.status = JobStatus.PENDING.value
            job.lease_expires_at = None
            job.progress_message = "Recovered after worker lease expired"
            if job.dispatch is None:
                raise RuntimeError("running_job_without_dispatch")
            job.dispatch.status = JobDispatchStatus.PENDING.value
            job.dispatch.available_at = now
            job.dispatch.published_at = None
            job.dispatch.last_error_code = None
            job.dispatch.last_error_detail = None
        db.flush()
        return len(expired_jobs)

    @staticmethod
    def complete(
        db: Session,
        *,
        job_id: uuid.UUID,
        result: dict[str, JsonValue] | None,
    ) -> tuple[DurableJob, bool]:
        job = db.scalar(
            select(DurableJob).where(DurableJob.id == job_id).with_for_update()
        )
        if job is None:
            raise AppError(
                code="job_not_found",
                message="Job not found",
                status_code=404,
            )
        if job.status == JobStatus.COMPLETED.value:
            return job, False
        if job.status == JobStatus.CANCELLED.value:
            return job, False
        job.status = JobStatus.COMPLETED.value
        job.result = result
        job.error_code = None
        job.completed_at = datetime.now(UTC)
        job.lease_expires_at = None
        db.flush()
        return job, True

    @staticmethod
    def fail(
        db: Session,
        *,
        job_id: uuid.UUID,
        error_code: str,
        result: dict[str, JsonValue] | None = None,
    ) -> tuple[DurableJob, bool]:
        job = db.scalar(
            select(DurableJob).where(DurableJob.id == job_id).with_for_update()
        )
        if job is None:
            raise AppError(
                code="job_not_found",
                message="Job not found",
                status_code=404,
            )
        if job.status in (JobStatus.COMPLETED.value, JobStatus.CANCELLED.value):
            return job, False
        job.status = JobStatus.FAILED.value
        job.result = result
        job.error_code = error_code
        job.completed_at = datetime.now(UTC)
        job.lease_expires_at = None
        db.flush()
        return job, True

    @staticmethod
    def pending_dispatches(
        db: Session,
        *,
        limit: int,
    ) -> list[JobDispatch]:
        return list(
            db.scalars(
                select(JobDispatch)
                .where(
                    JobDispatch.status == JobDispatchStatus.PENDING.value,
                    JobDispatch.available_at <= datetime.now(UTC),
                )
                .order_by(JobDispatch.available_at, JobDispatch.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )


job_repository = JobRepository()
