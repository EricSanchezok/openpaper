from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.modules.papers.application.ingestion import (
    IngestionReservation,
    IngestPaper,
)
from app.shared.application import Actor
from app.shared.domain import AppError


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


@pytest.mark.asyncio
async def test_ingestion_runs_one_shared_validation_and_dispatch_flow() -> None:
    validator = MagicMock()
    limits = MagicMock()
    limits.enforce_rate = AsyncMock()
    limits.acquire = AsyncMock()
    gateway = MagicMock()
    gateway.reserve.return_value = IngestionReservation(
        job_id=uuid4(),
        replayed=False,
    )
    gateway.dispatch = AsyncMock()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
    )

    response = await ingestion.from_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        project_id=None,
        idempotency_key=" request-1 ",
        ip_address="127.0.0.1",
    )

    validator.validate.assert_called_once()
    assert gateway.reserve.call_args.kwargs["idempotency_key"] == "request-1"
    limits.acquire.assert_awaited_once()
    gateway.dispatch.assert_awaited_once()
    assert response.job_id == gateway.reserve.return_value.job_id


@pytest.mark.asyncio
async def test_idempotent_ingestion_replay_does_not_dispatch_twice() -> None:
    validator = MagicMock()
    limits = MagicMock()
    limits.enforce_rate = AsyncMock()
    limits.acquire = AsyncMock()
    gateway = MagicMock()
    gateway.reserve.return_value = IngestionReservation(
        job_id=uuid4(),
        replayed=True,
    )
    gateway.dispatch = AsyncMock()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
    )

    await ingestion.from_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        project_id=None,
        idempotency_key="request-1",
        ip_address="127.0.0.1",
    )

    limits.acquire.assert_not_awaited()
    gateway.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrency_failure_marks_reserved_job_failed() -> None:
    validator = MagicMock()
    limits = MagicMock()
    limits.enforce_rate = AsyncMock()
    limits.acquire = AsyncMock(
        side_effect=AppError(
            code="background_concurrency_limit",
            message="Too many jobs",
            status_code=429,
        )
    )
    gateway = MagicMock()
    gateway.reserve.return_value = IngestionReservation(
        job_id=uuid4(),
        replayed=False,
    )
    gateway.dispatch = AsyncMock()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
    )

    with pytest.raises(AppError):
        await ingestion.from_bytes(
            actor=_actor(),
            content=b"%PDF fixture",
            filename="fixture.pdf",
            project_id=None,
            idempotency_key=None,
            ip_address="127.0.0.1",
        )

    gateway.fail.assert_called_once_with(
        actor=_actor(),
        job_id=gateway.reserve.return_value.job_id,
        error_code="background_concurrency_limit",
    )
    gateway.dispatch.assert_not_awaited()
