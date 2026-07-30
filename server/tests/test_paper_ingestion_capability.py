from unittest.mock import AsyncMock, MagicMock, patch
from typing import cast
from uuid import uuid4

import pytest
from app.modules.papers.application.ingestion import (
    IngestionFinalization,
    IngestionReservation,
    IngestPaper,
    ReapedStaleIngestion,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind
from app.modules.operation_journal.domain import OperationChange
from app.bootstrap.adapters.paper_ingestion import SqlPaperIngestionGateway
from app.bootstrap.adapters.upload_lifecycle import ReapedStaleUpload
from app.bootstrap.adapters.upload_reservations import UploadReservationResult
from app.database.models import (
    DurableJob,
    JobOperation,
    JobStatus,
    UploadReservation,
)


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


class FakeJournal:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def append(self, **entry: object) -> object:
        self.entries.append(entry)
        return object()

    def append_many(
        self,
        *,
        actor: object,
        operation: object,
        changes: object,
    ) -> tuple[object, ...]:
        del actor, operation
        normalized = tuple(changes)  # type: ignore[arg-type]
        self.entries.extend({"change": change} for change in normalized)
        return tuple(object() for _ in normalized)


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
    journal = FakeJournal()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
        journal=journal,  # type: ignore[arg-type]
    )

    prepared = await ingestion.prepare_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        ip_address="127.0.0.1",
    )
    operation = _operation()
    reservation = ingestion.reserve(
        actor=_actor(),
        operation=operation,
        prepared=prepared,
        project_id=None,
        idempotency_key=" request-1 ",
    )
    await ingestion.acquire(actor=_actor(), job_id=reservation.job_id)
    document_id = uuid4()
    gateway.finalize.return_value = IngestionFinalization(
        task_id=str(reservation.job_id),
        job_id=reservation.job_id,
        document_id=document_id,
        project_id=None,
        changed=True,
        job_completed=False,
    )
    task_id = ingestion.finalize(
        actor=_actor(),
        operation=operation,
        job_id=reservation.job_id,
        prepared=prepared,
    )

    validator.validate.assert_called_once()
    assert gateway.reserve.call_args.kwargs["idempotency_key"] == "request-1"
    limits.acquire.assert_awaited_once()
    gateway.finalize.assert_called_once()
    assert task_id.task_id == str(gateway.reserve.return_value.job_id)
    assert len(journal.entries) == 2
    assert gateway.reserve.call_args.kwargs["correlation_id"] == (
        operation.trace.correlation_id
    )
    assert gateway.reserve.call_args.kwargs["origin_operation_id"] == (
        operation.trace.operation_id
    )


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
    journal = FakeJournal()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
        journal=journal,  # type: ignore[arg-type]
    )

    prepared = await ingestion.prepare_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        ip_address="127.0.0.1",
    )
    reservation = ingestion.reserve(
        actor=_actor(),
        operation=_operation(),
        prepared=prepared,
        project_id=None,
        idempotency_key="request-1",
    )

    assert reservation.replayed
    assert journal.entries == []
    limits.acquire.assert_not_awaited()
    gateway.finalize.assert_not_called()


def test_reservation_journals_reaped_upload_changes_atomically() -> None:
    stale_job_id = uuid4()
    stale_document_id = uuid4()
    stale_project_id = uuid4()
    gc_job_id = uuid4()
    reservation_job_id = uuid4()
    gateway = MagicMock()
    gateway.reserve.return_value = IngestionReservation(
        job_id=reservation_job_id,
        replayed=False,
        reaped_stale_uploads=(
            ReapedStaleIngestion(
                job_id=stale_job_id,
                document_id=stale_document_id,
                project_id=stale_project_id,
                reference_removed=True,
                document_processing_failed=True,
                created_gc_job_id=gc_job_id,
            ),
        ),
    )
    journal = FakeJournal()
    ingestion = IngestPaper(
        validator=MagicMock(),
        limits=MagicMock(),
        gateway=gateway,
        journal=journal,  # type: ignore[arg-type]
    )

    ingestion.reserve(
        actor=_actor(),
        operation=_operation(),
        prepared=MagicMock(content=b"%PDF", filename="paper.pdf"),
        project_id=None,
        idempotency_key=None,
    )

    actions = [
        str(cast(OperationChange, entry["change"]).action)
        for entry in journal.entries
        if "change" in entry
    ]
    assert actions == [
        "job.failed",
        "document.processing_failed",
        "project.paper_removed",
        "job.created",
        "job.created",
    ]


def test_sql_ingestion_gateway_preserves_reaped_change_facts() -> None:
    actor = _actor()
    reservation_job_id = uuid4()
    durable_job = DurableJob(
        id=reservation_job_id,
        operation=JobOperation.PDF_PROCESS.value,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        requested_by_id=actor.id,
        idempotency_key=f"pdf-reservation:{reservation_job_id}",
        status=JobStatus.PENDING.value,
        payload={},
    )
    reservation = UploadReservation(id=reservation_job_id, quota_owner_id=actor.id)
    reservation.job = durable_job
    reaped = ReapedStaleUpload(
        job_id=uuid4(),
        document_id=uuid4(),
        project_id=None,
        reference_removed=True,
        document_processing_failed=True,
        created_gc_job_id=uuid4(),
    )
    gateway = SqlPaperIngestionGateway(MagicMock())

    with patch(
        "app.bootstrap.adapters.paper_ingestion.reserve_upload",
        return_value=UploadReservationResult(
            reservation=reservation,
            reaped_stale_uploads=(reaped,),
        ),
    ):
        result = gateway.reserve(
            actor=actor,
            correlation_id=uuid4(),
            origin_operation_id=uuid4(),
            project_id=None,
            content=b"%PDF",
            filename="paper.pdf",
            idempotency_key=None,
        )

    assert result.job_id == reservation_job_id
    assert len(result.reaped_stale_uploads) == 1
    assert result.reaped_stale_uploads[0].job_id == reaped.job_id
    assert result.reaped_stale_uploads[0].reference_removed


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
    gateway.fail.return_value = True
    journal = FakeJournal()
    ingestion = IngestPaper(
        validator=validator,
        limits=limits,
        gateway=gateway,
        journal=journal,  # type: ignore[arg-type]
    )

    prepared = await ingestion.prepare_bytes(
        actor=_actor(),
        content=b"%PDF fixture",
        filename="fixture.pdf",
        ip_address="127.0.0.1",
    )
    reservation = ingestion.reserve(
        actor=_actor(),
        operation=_operation(),
        prepared=prepared,
        project_id=None,
        idempotency_key=None,
    )
    with pytest.raises(AppError):
        await ingestion.acquire(actor=_actor(), job_id=reservation.job_id)

    ingestion.fail(
        actor=_actor(),
        operation=_operation(),
        job_id=reservation.job_id,
        error_code="background_concurrency_limit",
    )
    gateway.fail.assert_called_once_with(
        actor=_actor(),
        job_id=reservation.job_id,
        error_code="background_concurrency_limit",
    )
    gateway.finalize.assert_not_called()
    assert len(journal.entries) == 2
