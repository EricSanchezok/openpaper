from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.jobs.application.contracts import (
    CreateAudioOverviewRequest,
    CreateJobResponse,
    JobResponse,
)
from app.modules.jobs.application.jobs import EnqueueJobCommand, EnqueuedJob
from app.modules.papers.application.content import AccessiblePaperContent
from app.modules.research.application.generation import ResearchGeneration
from app.bootstrap.workflows.research_generation import ResearchGenerationWorkflow
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


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        display_name="Researcher",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _document() -> AccessiblePaperContent:
    return AccessiblePaperContent(
        document_id=uuid4(),
        original_filename="paper.pdf",
        title="Paper",
        abstract=None,
        raw_content="body",
        storage_key="papers/source.pdf",
        parser_markdown_storage_key="papers/content.md",
    )


def _job(job_id: UUID) -> JobResponse:
    return JobResponse(
        id=job_id,
        operation="audio_generate",
        document_id=None,
        project_id=None,
        status="pending",
        progress_message=None,
        error_code=None,
        result=None,
        created_at=datetime.now(UTC),
        started_at=None,
        completed_at=None,
    )


class FakeDocuments:
    def __init__(self, document: AccessiblePaperContent) -> None:
        self.value = document

    def document(self, **_kwargs: object) -> AccessiblePaperContent:
        return self.value

    def project(self, **_kwargs: object) -> list[AccessiblePaperContent]:
        return [self.value]


class FakeJobs:
    def __init__(self) -> None:
        self.existing: JobResponse | None = None
        self.fail_enqueue = False
        self.created = True
        self.commands: list[EnqueueJobCommand] = []

    def find_by_idempotency_key(self, *, key: str) -> JobResponse | None:
        assert key
        return self.existing

    def enqueue(self, *, command: EnqueueJobCommand) -> EnqueuedJob:
        self.commands.append(command)
        if self.fail_enqueue:
            raise RuntimeError("outbox_unavailable")
        return EnqueuedJob(job=_job(command.job_id), created=self.created)


class FakeEntitlements:
    def __init__(self) -> None:
        self.required_tokens = 0

    def require_tokens(self, **_kwargs: object) -> None:
        self.required_tokens += 1


class FakeJournal:
    def __init__(self) -> None:
        self.entries: list[dict[str, object]] = []

    def append(self, **entry: object) -> object:
        self.entries.append(entry)
        return object()


class FakeCapacity:
    def __init__(self) -> None:
        self.acquired_audio: list[UUID] = []
        self.released_audio: list[UUID] = []

    async def enforce_rate(self, **_kwargs: object) -> None:
        return None

    async def acquire_audio(
        self,
        *,
        operation_id: UUID,
        **_kwargs: object,
    ) -> None:
        self.acquired_audio.append(operation_id)

    async def acquire_background(self, **_kwargs: object) -> None:
        return None

    async def release_audio(
        self,
        *,
        operation_id: UUID,
        **_kwargs: object,
    ) -> None:
        self.released_audio.append(operation_id)

    async def release_background(self, **_kwargs: object) -> None:
        return None


class FakeExecutor:
    def __init__(self, generation: ResearchGeneration) -> None:
        self.capabilities = SimpleNamespace(research_generation=generation)
        self.phases: list[str] = []

    def query(self, operation: Any) -> Any:
        self.phases.append("query")
        return operation(self.capabilities)

    def command(self, operation: Any) -> Any:
        self.phases.append("command")
        return operation(self.capabilities)


def test_audio_idempotency_replays_without_reserving_capacity() -> None:
    jobs = FakeJobs()
    existing = _job(uuid4())
    jobs.existing = existing
    entitlements = FakeEntitlements()
    journal = FakeJournal()
    generation = ResearchGeneration(
        documents=FakeDocuments(_document()),  # type: ignore[arg-type]
        jobs=jobs,
        entitlements=entitlements,
        journal=journal,  # type: ignore[arg-type]
    )

    result = generation.prepare_document_audio(
        actor=_actor(),
        operation=_operation(),
        document_id=uuid4(),
        request=CreateAudioOverviewRequest(),
        idempotency_key="same-request",
    )

    assert isinstance(result, CreateJobResponse)
    assert result.job.id == existing.id
    assert entitlements.required_tokens == 0
    assert jobs.commands == []
    assert journal.entries == []


def test_enqueue_persists_causality_and_journals_only_a_new_job() -> None:
    jobs = FakeJobs()
    journal = FakeJournal()
    operation = _operation()
    actor = _actor()
    generation = ResearchGeneration(
        documents=FakeDocuments(_document()),  # type: ignore[arg-type]
        jobs=jobs,
        entitlements=FakeEntitlements(),
        journal=journal,  # type: ignore[arg-type]
    )
    prepared = generation.prepare_document_audio(
        actor=actor,
        operation=operation,
        document_id=uuid4(),
        request=CreateAudioOverviewRequest(),
        idempotency_key="new-request",
    )
    assert not isinstance(prepared, CreateJobResponse)
    assert prepared.command.correlation_id == operation.trace.correlation_id
    assert prepared.command.origin_operation_id == operation.trace.operation_id

    generation.enqueue(actor=actor, operation=operation, prepared=prepared)
    assert len(journal.entries) == 1

    jobs.created = False
    generation.enqueue(actor=actor, operation=operation, prepared=prepared)
    assert len(journal.entries) == 1


@pytest.mark.asyncio
async def test_audio_releases_external_capacity_when_outbox_enqueue_fails() -> None:
    jobs = FakeJobs()
    jobs.fail_enqueue = True
    entitlements = FakeEntitlements()
    capacity = FakeCapacity()
    generation = ResearchGeneration(
        documents=FakeDocuments(_document()),  # type: ignore[arg-type]
        jobs=jobs,
        entitlements=entitlements,
        journal=FakeJournal(),  # type: ignore[arg-type]
    )
    executor = FakeExecutor(generation)
    workflow = ResearchGenerationWorkflow(
        executor=executor,  # type: ignore[arg-type]
        capacity=capacity,
        operation_factory=OperationContextFactory(),
    )

    with pytest.raises(RuntimeError, match="outbox_unavailable"):
        await workflow.run(
            actor=_actor(),
            operation=_operation(),
            client_ip="127.0.0.1",
            prepare=lambda capability, operation: capability.prepare_document_audio(
                actor=_actor(),
                operation=operation,
                document_id=uuid4(),
                request=CreateAudioOverviewRequest(),
                idempotency_key="new-request",
            ),
        )

    assert entitlements.required_tokens == 1
    assert capacity.released_audio == capacity.acquired_audio
    assert executor.phases == ["query", "command"]
