from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.bootstrap.workflows.discovery import PaperDiscoveryWorkflow
from app.modules.papers.application.contracts.discovery import (
    DiscoveryPaperListResponse,
    OpenAlexCitationGraph,
    OpenAlexResponse,
    OpenAlexWork,
)
from app.modules.papers.application.discovery import (
    AccessibleDiscoveryDocument,
    DiscoverPapers,
    DiscoveryMatchPreparation,
    DiscoveryMatchResult,
)
from app.modules.operation_journal.domain import OperationAction
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
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _graph() -> OpenAlexCitationGraph:
    center = OpenAlexWork(id="W1", title="A paper")
    empty = OpenAlexResponse(meta={"count": 0}, results=[])
    return OpenAlexCitationGraph(center=center, cites=empty, cited_by=empty)


class _DiscoveryCapability:
    def __init__(self, executor: _BoundaryExecutor) -> None:
        self._executor = executor
        self.completed_operation: OperationContext | None = None

    def prepare_match(
        self,
        *,
        actor: Actor,
        doi: str | None,
        document_id: UUID | None,
    ) -> DiscoveryMatchPreparation:
        assert self._executor.active
        assert actor.id == 7
        assert doi is None
        assert document_id is not None
        return DiscoveryMatchPreparation(
            document=AccessibleDiscoveryDocument(
                document_id=document_id,
                title="A paper",
                doi=None,
            ),
            doi=None,
        )

    def complete_match(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        preparation: DiscoveryMatchPreparation,
        result: DiscoveryMatchResult,
    ) -> OpenAlexCitationGraph:
        assert self._executor.active
        assert actor.id == 7
        assert preparation.document is not None
        self.completed_operation = operation
        return result.graph


class _Capabilities:
    def __init__(self, discovery: _DiscoveryCapability) -> None:
        self.paper_discovery = discovery


class _BoundaryExecutor:
    def __init__(self) -> None:
        self.active = False
        self.query_count = 0
        self.command_count = 0
        self.command_async_count = 0
        self.discovery = _DiscoveryCapability(self)
        self.capabilities = _Capabilities(self.discovery)

    def query(self, callback: Callable[[Any], Any]) -> Any:
        assert not self.active
        self.active = True
        self.query_count += 1
        try:
            return callback(self.capabilities)
        finally:
            self.active = False

    def command(self, callback: Callable[[Any], Any]) -> Any:
        assert not self.active
        self.active = True
        self.command_count += 1
        try:
            return callback(self.capabilities)
        finally:
            self.active = False

    async def command_async(self, _callback: object) -> object:
        self.command_async_count += 1
        raise AssertionError("external discovery must not use command_async")


class _ExternalDiscovery:
    def __init__(self, executor: _BoundaryExecutor) -> None:
        self._executor = executor
        self.match_recorded = False

    def prepare_search(
        self,
        *,
        actor: Actor,
        query: str,
        cursor: str | None,
    ) -> tuple[str, str | None]:
        assert not self._executor.active
        assert actor.id == 7
        return query, cursor

    async def search(
        self,
        *,
        actor: Actor,
        client_ip: str,
        preparation: tuple[str, str | None],
    ) -> DiscoveryPaperListResponse:
        assert not self._executor.active
        assert actor.id == 7
        assert client_ip == "127.0.0.1"
        assert preparation == ("graph learning", None)
        return DiscoveryPaperListResponse(items=[])

    def prepare_author_works(
        self,
        *,
        actor: Actor,
        author_id: str,
        cursor: str | None,
    ) -> tuple[str, str | None]:
        assert not self._executor.active
        return author_id, cursor

    async def author_works(
        self,
        *,
        actor: Actor,
        client_ip: str,
        preparation: tuple[str, str | None],
    ) -> DiscoveryPaperListResponse:
        assert not self._executor.active
        return DiscoveryPaperListResponse(items=[])

    async def fetch_match(
        self,
        *,
        actor: Actor,
        client_ip: str,
        preparation: DiscoveryMatchPreparation,
    ) -> DiscoveryMatchResult:
        assert not self._executor.active
        assert preparation.document is not None
        return DiscoveryMatchResult(
            graph=_graph(),
            resolved_doi="10.1000/example",
        )

    def record_match(
        self,
        *,
        actor: Actor,
        result: DiscoveryMatchResult,
    ) -> None:
        assert not self._executor.active
        self.match_recorded = True


@pytest.mark.asyncio
async def test_search_performs_no_application_transaction() -> None:
    executor = _BoundaryExecutor()
    external = _ExternalDiscovery(executor)
    workflow = PaperDiscoveryWorkflow(
        executor=executor,  # type: ignore[arg-type]
        external=external,  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
    )

    result = await workflow.search(
        actor=_actor(),
        client_ip="127.0.0.1",
        query="graph learning",
        cursor=None,
    )

    assert result.items == []
    assert executor.query_count == 0
    assert executor.command_count == 0
    assert executor.command_async_count == 0


@pytest.mark.asyncio
async def test_match_uses_short_prepare_and_apply_transactions() -> None:
    executor = _BoundaryExecutor()
    external = _ExternalDiscovery(executor)
    workflow = PaperDiscoveryWorkflow(
        executor=executor,  # type: ignore[arg-type]
        external=external,  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
    )
    operation = _operation()

    result = await workflow.match(
        actor=_actor(),
        operation=operation,
        client_ip="127.0.0.1",
        doi=None,
        document_id=uuid4(),
    )

    assert result.center.id == "W1"
    assert executor.query_count == 1
    assert executor.command_count == 1
    assert executor.command_async_count == 0
    completed_operation = executor.discovery.completed_operation
    assert completed_operation is not None
    assert completed_operation.initiated_by is OperationInitiator.SYSTEM
    assert completed_operation.trace.correlation_id == operation.trace.correlation_id
    assert completed_operation.trace.causation_id == operation.trace.operation_id
    assert external.match_recorded


class _Documents:
    def __init__(self, *, changed: bool) -> None:
        self.changed = changed

    def find_accessible(self, **_kwargs: object) -> None:
        return None

    def set_doi(self, **_kwargs: object) -> bool:
        return self.changed


class _Journal:
    def __init__(self) -> None:
        self.actions: list[OperationAction] = []

    def append(self, **kwargs: object) -> None:
        self.actions.append(OperationAction(kwargs["action"]))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("changed", "expected_actions"),
    [
        (False, []),
        (True, [OperationAction("paper.doi_updated")]),
    ],
)
def test_complete_match_journals_only_a_real_doi_change(
    changed: bool,
    expected_actions: list[OperationAction],
) -> None:
    document_id = uuid4()
    documents = _Documents(changed=changed)
    journal = _Journal()
    capability = DiscoverPapers(
        documents=documents,
        journal=journal,  # type: ignore[arg-type]
    )

    capability.complete_match(
        actor=_actor(),
        operation=_operation(),
        preparation=DiscoveryMatchPreparation(
            document=AccessibleDiscoveryDocument(
                document_id=document_id,
                title="A paper",
                doi=None,
            ),
            doi=None,
        ),
        result=DiscoveryMatchResult(
            graph=_graph(),
            resolved_doi="10.1000/example",
        ),
    )

    assert journal.actions == expected_actions
