import inspect
from uuid import uuid4

import pytest

from app.modules.jobs.application.causality import (
    JobCausalityFacts,
    require_job_causality_owner,
)
from app.modules.jobs.infrastructure.causality import SqlAlchemyJobCausalityResolver
from app.modules.jobs.infrastructure.models import DurableJob
from app.modules.jobs.infrastructure.repository import CreateJob
from app.shared.application import Actor
from app.shared.domain import AppError
from app.shared.domain.enums import JobOperation


def _actor(actor_id: int = 7) -> Actor:
    return Actor(
        id=actor_id,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def test_job_causality_owner_requires_the_persisted_owner() -> None:
    facts = JobCausalityFacts(
        job_id=uuid4(),
        operation=JobOperation.PDF_POSTPROCESS,
        requested_by_id=7,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )

    require_job_causality_owner(facts=facts, actor=_actor())

    with pytest.raises(AppError, match="job_owner_mismatch"):
        require_job_causality_owner(facts=facts, actor=_actor(8))
    with pytest.raises(AppError, match="job_owner_mismatch"):
        require_job_causality_owner(facts=facts, actor=None)


def test_system_owned_job_rejects_an_actor_pairing() -> None:
    facts = JobCausalityFacts(
        job_id=uuid4(),
        operation=JobOperation.DOCUMENT_GC,
        requested_by_id=None,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )

    require_job_causality_owner(facts=facts, actor=None)
    with pytest.raises(AppError, match="job_owner_mismatch"):
        require_job_causality_owner(facts=facts, actor=_actor())


def test_jobs_persist_non_nullable_scalar_causality() -> None:
    assert DurableJob.__table__.c.correlation_id.nullable is False
    assert DurableJob.__table__.c.origin_operation_id.nullable is False
    required = {
        parameter.name
        for parameter in inspect.signature(CreateJob).parameters.values()
        if parameter.default is inspect.Parameter.empty
    }
    assert {"correlation_id", "origin_operation_id"} <= required


def test_job_causality_resolver_is_read_only_and_context_free() -> None:
    source = inspect.getsource(SqlAlchemyJobCausalityResolver)
    assert "OperationContext" not in source
    assert ".add(" not in source
    assert ".flush(" not in source
    assert ".commit(" not in source
