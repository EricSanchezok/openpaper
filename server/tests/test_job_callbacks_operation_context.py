"""Durable Job terminal changes share one resumed operation journal."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.jobs.application.callbacks import (
    JobCallbacks,
    JobHandlerResult,
    RegisteredJobCallback,
    ScheduledZoteroJobs,
)
from app.modules.jobs.application.contracts import JobCallbackIdentity
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    OperationJournalEntry,
    ResourceRef,
)
from app.shared.application import (
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)
from app.shared.domain.enums import JobOperation, JobStatus
from app.transport.http.internal_v1.references import job_delivery_reference
from pydantic import BaseModel


class _Clock:
    def now(self) -> datetime:
        return datetime(2026, 7, 31, tzinfo=UTC)


class _Store:
    def __init__(self) -> None:
        self.entries: list[OperationJournalEntry] = []

    def append(self, entries: tuple[OperationJournalEntry, ...]) -> None:
        self.entries.extend(entries)


class _Lifecycle:
    def __init__(self, *, status: JobStatus) -> None:
        self.status_value = status

    def operation(self, *, job_id: UUID) -> JobOperation:
        return JobOperation.PDF_POSTPROCESS

    def status(self, *, job_id: UUID) -> JobStatus:
        return self.status_value

    def claim(self, *, job_id: UUID) -> bool:
        return False

    def heartbeat(self, *, job_id: UUID) -> bool:
        return False

    def fail(self, *, job_id: UUID, error_code: str) -> bool:
        self.status_value = JobStatus.FAILED
        return True


class _Handler:
    def __init__(self, lifecycle: _Lifecycle, document_id: UUID) -> None:
        self._lifecycle = lifecycle
        self._document_id = document_id

    async def complete(
        self,
        *,
        actor: object,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        self._lifecycle.status_value = JobStatus.COMPLETED
        return JobHandlerResult(
            value={"completed": True},
            changes=(
                OperationChange(
                    action=OperationAction("document.metadata_hydrated"),
                    resources=(ResourceRef("document", str(self._document_id)),),
                ),
            ),
        )


class _ReplayHandler:
    async def complete(
        self,
        *,
        actor: object,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        return JobHandlerResult(value={"completed": False})


class _Schedules:
    def schedule_zotero_sync(
        self,
        *,
        threshold_seconds: int,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> ScheduledZoteroJobs:
        raise AssertionError("not used")


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("job_test", uuid4()),
        credential=None,
    )


def test_job_delivery_reference_is_canonical_and_non_sensitive() -> None:
    reference = job_delivery_reference("worker-delivery-nonce")

    assert len(reference) == 64
    assert reference == job_delivery_reference("worker-delivery-nonce")
    assert "worker-delivery-nonce" not in reference


@pytest.mark.asyncio
async def test_job_completion_journals_business_and_terminal_changes_once() -> None:
    job_id = uuid4()
    document_id = uuid4()
    lifecycle = _Lifecycle(status=JobStatus.RUNNING)
    store = _Store()
    callbacks = JobCallbacks(
        lifecycle=lifecycle,
        handlers={
            JobOperation.PDF_POSTPROCESS: RegisteredJobCallback(
                contract=JobCallbackIdentity,
                handler=_Handler(lifecycle, document_id),
            )
        },
        schedules=_Schedules(),
        journal=OperationJournal(store=store, clock=_Clock()),
    )

    result = await callbacks.complete(
        actor=None,
        operation=_operation(),
        job_id=job_id,
        payload={"task_id": str(job_id)},
    )

    assert result.value == {"completed": True}
    assert {str(entry.action) for entry in store.entries} == {
        "document.metadata_hydrated",
        "job.completed",
    }


@pytest.mark.asyncio
async def test_job_completion_replay_does_not_append_a_terminal_entry() -> None:
    job_id = uuid4()
    store = _Store()
    callbacks = JobCallbacks(
        lifecycle=_Lifecycle(status=JobStatus.COMPLETED),
        handlers={
            JobOperation.PDF_POSTPROCESS: RegisteredJobCallback(
                contract=JobCallbackIdentity,
                handler=_ReplayHandler(),
            )
        },
        schedules=_Schedules(),
        journal=OperationJournal(store=store, clock=_Clock()),
    )

    await callbacks.complete(
        actor=None,
        operation=_operation(),
        job_id=job_id,
        payload={"task_id": str(job_id)},
    )

    assert store.entries == []
