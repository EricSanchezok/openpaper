"""Purpose-built read-only resolver for persisted Job causality."""

from __future__ import annotations

from uuid import UUID

from app.modules.jobs.application.causality import JobCausalityFacts
from app.modules.jobs.infrastructure.models import DurableJob
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobOperation
from sqlalchemy import select
from sqlalchemy.orm import Session


class SqlAlchemyJobCausalityResolver:
    def __init__(self, db: Session) -> None:
        self._db = db

    def resolve(self, *, job_id: UUID) -> JobCausalityFacts:
        row = self._db.execute(
            select(
                DurableJob.id,
                DurableJob.operation,
                DurableJob.requested_by_id,
                DurableJob.correlation_id,
                DurableJob.origin_operation_id,
            ).where(DurableJob.id == job_id)
        ).one_or_none()
        if row is None:
            raise AppError(
                code="job_not_found",
                message="Job not found",
                kind=FailureKind.NOT_FOUND,
            )
        return JobCausalityFacts(
            job_id=row.id,
            operation=JobOperation(row.operation),
            requested_by_id=row.requested_by_id,
            correlation_id=row.correlation_id,
            origin_operation_id=row.origin_operation_id,
        )


__all__ = ["SqlAlchemyJobCausalityResolver"]
