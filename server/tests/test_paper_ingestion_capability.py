from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.modules.papers.application.ingestion import (
    IngestionReservation,
    IngestPaper,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


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
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
    )

    prepared = await ingestion.prepare_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        ip_address="127.0.0.1",
    )
    reservation = ingestion.reserve(
        actor=_actor(),
        prepared=prepared,
        project_id=None,
        idempotency_key=" request-1 ",
    )
    await ingestion.acquire(actor=_actor(), job_id=reservation.job_id)
    gateway.finalize.return_value = str(reservation.job_id)
    task_id = ingestion.finalize(
        actor=_actor(),
        job_id=reservation.job_id,
        prepared=prepared,
    )

    validator.validate.assert_called_once()
    assert gateway.reserve.call_args.kwargs["idempotency_key"] == "request-1"
    limits.acquire.assert_awaited_once()
    gateway.finalize.assert_called_once()
    assert task_id == str(gateway.reserve.return_value.job_id)


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
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
    )

    prepared = await ingestion.prepare_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        ip_address="127.0.0.1",
    )
    reservation = ingestion.reserve(
        actor=_actor(),
        prepared=prepared,
        project_id=None,
        idempotency_key="request-1",
    )

    assert reservation.replayed
    limits.acquire.assert_not_awaited()
    gateway.finalize.assert_not_called()


@pytest.mark.asyncio
async def test_concurrency_failure_marks_reserved_job_failed() -> None:
    validator = MagicMock()
    limits = MagicMock()
    limits.enforce_rate = AsyncMock()
    limits.acquire = AsyncMock(
        side_effect=AppError(
            code="background_concurrency_limit",
            message="Too many jobs",
            kind=FailureKind.RATE_LIMITED,
        )
    )
    gateway = MagicMock()
    gateway.reserve.return_value = IngestionReservation(
        job_id=uuid4(),
        replayed=False,
    )
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
    )

    prepared = await ingestion.prepare_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        ip_address="127.0.0.1",
    )
    reservation = ingestion.reserve(
        actor=_actor(),
        prepared=prepared,
        project_id=None,
        idempotency_key=None,
    )
    with pytest.raises(AppError):
        await ingestion.acquire(actor=_actor(), job_id=reservation.job_id)

    ingestion.fail(
        actor=_actor(),
        job_id=reservation.job_id,
        error_code="background_concurrency_limit",
    )
    gateway.fail.assert_called_once_with(
        actor=_actor(),
        job_id=reservation.job_id,
        error_code="background_concurrency_limit",
    )
    gateway.finalize.assert_not_called()
