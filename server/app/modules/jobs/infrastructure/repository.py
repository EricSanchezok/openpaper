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
from app.shared.domain import AppError, FailureKind
from app.modules.jobs.domain import (
    DEFAULT_JOB_LEASE,
    can_complete_job,
    can_fail_job,
    can_recover_job,
)
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload


@dataclass(frozen=True, slots=True)
class CreateJob:
    operation: JobOperation
    requested_by_id: int | None
    correlation_id: uuid.UUID
    origin_operation_id: uuid.UUID
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


@dataclass(frozen=True, slots=True)
class PersistedJob:
    job: DurableJob
    created: bool


@dataclass(frozen=True, slots=True)
class ReservedJobDispatch:
    dispatch_id: uuid.UUID
    job_id: uuid.UUID
    task_name: str
    queue: str
    kwargs: dict[str, JsonValue]
    attempt_count: int
    enqueued_at: datetime
    correlation_id: uuid.UUID
    origin_operation_id: uuid.UUID
    requested_by_id: int | None


class JobRepository:
    @staticmethod
    def find_by_idempotency_key(
        db: Session,
        *,
        idempotency_key: str,
    ) -> DurableJob | None:
        return db.scalar(
            select(DurableJob).where(DurableJob.idempotency_key == idempotency_key)
        )

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

    def create(self, db: Session, *, request: CreateJob) -> PersistedJob:
        job_id = request.job_id or uuid.uuid4()
        inserted_id = db.scalar(
            insert(DurableJob)
            .values(
                id=job_id,
                operation=request.operation.value,
                correlation_id=request.correlation_id,
                origin_operation_id=request.origin_operation_id,
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
            return PersistedJob(job=existing, created=False)

        job = db.get(DurableJob, inserted_id)
        if job is None:
            raise RuntimeError("inserted_job_not_found")
        return PersistedJob(job=job, created=True)

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

    def enqueue(self, db: Session, *, request: EnqueueJob) -> PersistedJob:
        persisted = self.create(db, request=request)
        job = persisted.job
        if job.dispatch is None:
            self.add_dispatch(
                db,
                job=job,
                task_name=request.task_name,
                queue=request.queue,
                kwargs=request.task_kwargs,
                available_at=request.available_at,
            )
        return persisted

    @staticmethod
    def require(db: Session, *, job_id: uuid.UUID) -> DurableJob:
        job = db.get(DurableJob, job_id)
        if job is None:
            raise AppError(
                code="job_not_found",
                message="Job not found",
                kind=FailureKind.NOT_FOUND,
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
                kind=FailureKind.NOT_FOUND,
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
        db.flush()
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
            if not can_recover_job(
                JobStatus(job.status),
                lease_expires_at=job.lease_expires_at,
                now=now,
            ):
                raise RuntimeError("selected_job_is_not_recoverable")
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
                kind=FailureKind.NOT_FOUND,
            )
        if not can_complete_job(JobStatus(job.status)):
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
                kind=FailureKind.NOT_FOUND,
            )
        if not can_fail_job(JobStatus(job.status)):
            return job, False
        job.status = JobStatus.FAILED.value
        job.result = result
        job.error_code = error_code
        job.completed_at = datetime.now(UTC)
        job.lease_expires_at = None
        db.flush()
        return job, True

    @staticmethod
    def reserve_dispatches(
        db: Session,
        *,
        limit: int,
        lease: timedelta,
    ) -> tuple[ReservedJobDispatch, ...]:
        now = datetime.now(UTC)
        dispatches = list(
            db.scalars(
                select(JobDispatch)
                .options(selectinload(JobDispatch.job))
                .where(
                    or_(
                        and_(
                            JobDispatch.status == JobDispatchStatus.PENDING.value,
                            JobDispatch.available_at <= now,
                        ),
                        and_(
                            JobDispatch.status == JobDispatchStatus.PUBLISHING.value,
                            JobDispatch.available_at <= now,
                        ),
                    )
                )
                .order_by(JobDispatch.available_at, JobDispatch.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        reserved: list[ReservedJobDispatch] = []
        for dispatch in dispatches:
            job = dispatch.job
            dispatch.status = JobDispatchStatus.PUBLISHING.value
            dispatch.attempt_count += 1
            dispatch.available_at = now + lease
            reserved.append(
                ReservedJobDispatch(
                    dispatch_id=dispatch.id,
                    job_id=dispatch.job_id,
                    task_name=dispatch.task_name,
                    queue=dispatch.queue,
                    kwargs=dict(dispatch.kwargs),
                    attempt_count=dispatch.attempt_count,
                    enqueued_at=dispatch.created_at,
                    correlation_id=job.correlation_id,
                    origin_operation_id=job.origin_operation_id,
                    requested_by_id=job.requested_by_id,
                )
            )
        db.flush()
        return tuple(reserved)

    @staticmethod
    def complete_dispatch(
        db: Session,
        *,
        dispatch_id: uuid.UUID,
        attempt_count: int,
    ) -> bool:
        now = datetime.now(UTC)
        changed = bool(
            db.execute(
                update(JobDispatch)
                .where(
                    JobDispatch.id == dispatch_id,
                    JobDispatch.status == JobDispatchStatus.PUBLISHING.value,
                    JobDispatch.attempt_count == attempt_count,
                )
                .values(
                    status=JobDispatchStatus.PUBLISHED.value,
                    published_at=now,
                    available_at=now,
                    last_error_code=None,
                    last_error_detail=None,
                )
            ).rowcount
        )
        db.flush()
        return changed

    @staticmethod
    def retry_dispatch(
        db: Session,
        *,
        dispatch_id: uuid.UUID,
        attempt_count: int,
        available_at: datetime,
        error_code: str,
        error_detail: str,
    ) -> bool:
        changed = bool(
            db.execute(
                update(JobDispatch)
                .where(
                    JobDispatch.id == dispatch_id,
                    JobDispatch.status == JobDispatchStatus.PUBLISHING.value,
                    JobDispatch.attempt_count == attempt_count,
                )
                .values(
                    status=JobDispatchStatus.PENDING.value,
                    available_at=available_at,
                    published_at=None,
                    last_error_code=error_code,
                    last_error_detail=error_detail,
                )
            ).rowcount
        )
        db.flush()
        return changed


job_repository = JobRepository()

__all__ = [
    "CreateJob",
    "EnqueueJob",
    "JobRepository",
    "PersistedJob",
    "ReservedJobDispatch",
    "job_repository",
]
