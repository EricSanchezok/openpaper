"""Read-only causality facts used to resume authenticated Job operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobOperation


@dataclass(frozen=True, slots=True)
class JobCausalityFacts:
    job_id: UUID
    operation: JobOperation
    requested_by_id: int | None
    correlation_id: UUID
    origin_operation_id: UUID


class JobCausalityResolver(Protocol):
    def resolve(self, *, job_id: UUID) -> JobCausalityFacts: ...


def require_job_causality_owner(
    *,
    facts: JobCausalityFacts,
    actor: Actor | None,
) -> None:
    """Prevent pairing a resumed Job trace with a different product owner."""
    actor_id = actor.id if actor is not None else None
    if actor_id != facts.requested_by_id:
        raise AppError(
            code="job_owner_mismatch",
            message="Job ownership could not be verified",
            kind=FailureKind.PERMISSION_DENIED,
        )


__all__ = [
    "JobCausalityFacts",
    "JobCausalityResolver",
    "require_job_causality_owner",
]
