"""PDF metadata recovery keeps provider I/O outside the finalize command."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.bootstrap.adapters.citation_provider import CitationProviderResult
from app.bootstrap.workflows.pdf_postprocess import (
    PdfPostprocessSnapshot,
    PdfPostprocessWorkflow,
)
from app.modules.jobs.application.callbacks import JobCompletionResult
from app.modules.papers.application.citations import CitationMetadataPatch
from app.modules.papers.domain.citations import CitationFields
from app.shared.application import (
    Actor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)


class _Reader:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def read(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        callback_task_id: UUID,
    ) -> PdfPostprocessSnapshot:
        assert callback_task_id == job_id
        self._events.append("read")
        return PdfPostprocessSnapshot(
            terminal=False,
            fields=CitationFields(title="A paper", authors=["Ada"]),
        )


class _Provider:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def deterministic(
        self,
        *,
        fields: CitationFields,
    ) -> CitationProviderResult:
        self._events.append("external")
        return CitationProviderResult(
            patch=CitationMetadataPatch(doi="10.1/example"),
            filled_fields={"doi": "10.1/example"},
        )

    def agentic(self, **kwargs: object) -> CitationProviderResult:
        return CitationProviderResult(
            patch=CitationMetadataPatch(journal="Journal"),
            filled_fields={"journal": "Journal"},
            confidence=0.9,
        )


class _Callbacks:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.operation: OperationContext | None = None
        self.resolution: object | None = None

    async def complete_pdf_postprocess(self, **kwargs: object) -> JobCompletionResult:
        self._events.append("finalize")
        self.operation = kwargs["operation"]  # type: ignore[assignment]
        self.resolution = kwargs["resolution"]
        return JobCompletionResult(value="done")


class _Capabilities:
    def __init__(self, callbacks: _Callbacks) -> None:
        self.job_callbacks = callbacks


class _Executor:
    def __init__(self, capabilities: _Capabilities) -> None:
        self._capabilities = capabilities

    async def command_async(self, operation: object) -> object:
        return await operation(self._capabilities)  # type: ignore[operator]


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_postprocess_test", uuid4()),
        credential=None,
    )


@pytest.mark.asyncio
async def test_pdf_postprocess_resolves_before_finalize_command() -> None:
    events: list[str] = []
    callbacks = _Callbacks(events)
    original = _operation()
    job_id = uuid4()
    workflow = PdfPostprocessWorkflow(
        executor=_Executor(_Capabilities(callbacks)),  # type: ignore[arg-type]
        reader=_Reader(events),
        provider=_Provider(events),  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
    )

    result = await workflow.complete(
        actor=_actor(),
        operation=original,
        job_id=job_id,
        payload={"task_id": str(job_id)},
    )

    assert result.value == "done"
    assert events == ["read", "external", "finalize"]
    assert callbacks.operation is not None
    assert callbacks.operation.trace.causation_id == original.trace.operation_id
    assert callbacks.resolution is not None
    assert callbacks.resolution.doi == "10.1/example"  # type: ignore[union-attr]
    assert callbacks.resolution.journal == "Journal"  # type: ignore[union-attr]
