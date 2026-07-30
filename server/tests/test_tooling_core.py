from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TypeVar
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import (
    WORKSPACE_PERMISSION_ORDER,
    AppError,
    FailureKind,
    JsonValue,
    WorkspacePermission,
)
from app.tooling import (
    ToolAccess,
    ToolExecutionContext,
    ToolCatalog,
    ToolDefinition,
    ToolDispatcher,
    ToolExecutionKind,
    ToolOutcome,
    ToolProfile,
)
from app.tooling.invocations import ToolInvocationGateway
from app.tooling.workspace import (
    CONVERSATION_TOOL_PROFILE,
    MCP_TOOL_PROFILE,
    build_workspace_tool_catalog,
)
from pydantic import BaseModel

ResultT = TypeVar("ResultT")


class Arguments(BaseModel):
    value: str


class MemoryInvocationGateway(ToolInvocationGateway):
    def __init__(self) -> None:
        self.items: dict[tuple[int, str], tuple[str, str, JsonValue]] = {}
        self.operation_ids: dict[tuple[int, str], UUID] = {}

    def replay(
        self,
        *,
        actor_id: int,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
    ) -> JsonValue | None:
        stored = self.items.get((actor_id, invocation_key))
        if stored is None:
            return None
        stored_name, stored_hash, result = stored
        if stored_name != tool_name or stored_hash != arguments_hash:
            raise AppError(
                code="tool_invocation_conflict",
                message="conflict",
                kind=FailureKind.CONFLICT,
            )
        return result

    def complete(
        self,
        *,
        actor_id: int,
        operation_id: UUID,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None:
        self.items[(actor_id, invocation_key)] = (
            tool_name,
            arguments_hash,
            result,
        )
        self.operation_ids[(actor_id, invocation_key)] = operation_id


@dataclass
class Capabilities:
    tool_invocations: MemoryInvocationGateway
    writes: int = 0


class Executor:
    def __init__(self, capabilities: Capabilities) -> None:
        self.capabilities = capabilities
        self.queries = 0
        self.commands = 0

    def query(self, operation: Callable[[Capabilities], ResultT]) -> ResultT:
        self.queries += 1
        return operation(self.capabilities)

    def command(self, operation: Callable[[Capabilities], ResultT]) -> ResultT:
        self.commands += 1
        return operation(self.capabilities)

    async def command_async(
        self,
        operation: Callable[[Capabilities], ResultT],
    ) -> ResultT:
        return operation(self.capabilities)


def _context() -> ToolExecutionContext:
    operation_factory = OperationContextFactory()
    request_operation = operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=RequestReference(uuid4()),
            conversation_id=uuid4(),
            turn_id=uuid4(),
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    return ToolExecutionContext(
        actor=Actor(
            id=1,
            email="user@example.com",
            status="active",
            email_verified=True,
        ),
        operation=operation_factory.child(
            request_operation,
            initiated_by=OperationInitiator.AGENT,
        ),
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="turn-1",
        client_ip="test",
    )


def _access(
    profile_name: str = "conversation",
    *permissions: WorkspacePermission,
) -> ToolAccess:
    return ToolAccess(
        profile_name=profile_name,
        permissions=frozenset(permissions or WORKSPACE_PERMISSION_ORDER),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("invocation_id", ""),
        ("invocation_id", "x" * 1025),
        ("client_ip", ""),
        ("client_ip", " 127.0.0.1 "),
        ("client_ip", "x" * 65),
    ],
)
def test_tool_execution_context_rejects_unbounded_ephemeral_values(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValueError):
        replace(_context(), **{field: value})


def test_profiles_are_independent_and_validate_references() -> None:
    query = ToolDefinition[Capabilities](
        name="query_tool",
        description="query",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        handler=lambda capabilities, context, arguments: ToolOutcome(
            payload={"value": arguments.value}
        ),
    )
    catalog = ToolCatalog(
        [query],
        [
            ToolProfile(name="conversation", tool_names=frozenset()),
            ToolProfile(name="mcp", tool_names=frozenset({"query_tool"})),
        ],
    )

    assert catalog.definitions_for(_access("conversation")) == []
    assert [item.name for item in catalog.definitions_for(_access("mcp"))] == [
        "query_tool"
    ]
    with pytest.raises(ValueError, match="missing tools"):
        ToolCatalog(
            [query],
            [ToolProfile(name="broken", tool_names=frozenset({"missing"}))],
        )


@pytest.mark.asyncio
async def test_dispatcher_maps_unknown_tools_and_invalid_arguments() -> None:
    definition = ToolDefinition[Capabilities](
        name="query_tool",
        description="query",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
        required_permission=WorkspacePermission.READ,
        handler=lambda capabilities, context, arguments: ToolOutcome(
            payload={"value": arguments.value}
        ),
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            [definition],
            [ToolProfile(name="conversation", tool_names=frozenset({"query_tool"}))],
        ),
        executor=Executor(capabilities),
    )

    with pytest.raises(AppError) as unknown:
        await dispatcher.dispatch(
            name="missing",
            raw_arguments={},
            context=_context(),
            access=_access(),
        )
    assert unknown.value.code == "tool_not_found"

    with pytest.raises(AppError) as invalid:
        await dispatcher.dispatch(
            name="query_tool",
            raw_arguments={},
            context=_context(),
            access=_access(),
        )
    assert invalid.value.code == "tool_arguments_invalid"
    assert invalid.value.kind is FailureKind.INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_command_dispatch_is_persistently_replayed() -> None:
    def write(
        capabilities: Capabilities,
        context: ToolExecutionContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del context
        parsed = Arguments.model_validate(arguments)
        capabilities.writes += 1
        return ToolOutcome(
            payload={"value": parsed.value},
            evidence={"paper-1": ["1: evidence"]},
            artifacts=[{"kind": "artifact"}],
            action={"kind": "write"},
        )

    definition = ToolDefinition[Capabilities](
        name="write_tool",
        description="write",
        input_model=Arguments,
        execution=ToolExecutionKind.COMMAND,
        required_permission=WorkspacePermission.WRITE,
        handler=write,
    )
    catalog = ToolCatalog(
        [definition],
        [ToolProfile(name="conversation", tool_names=frozenset({"write_tool"}))],
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    executor = Executor(capabilities)
    dispatcher = ToolDispatcher(catalog=catalog, executor=executor)
    context = _context()

    first = await dispatcher.dispatch(
        name="write_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )
    second = await dispatcher.dispatch(
        name="write_tool",
        raw_arguments={"value": "same"},
        context=context,
        access=_access(),
    )

    assert first.payload == {"value": "same"}
    assert second.payload == {"value": "same"}
    assert second.evidence == first.evidence
    assert second.artifacts == first.artifacts
    assert second.action == {"kind": "write"}
    assert capabilities.writes == 1
    assert executor.commands == 2
    assert (
        capabilities.tool_invocations.operation_ids[
            (context.actor.id, f"{context.invocation_id}:write_tool")
        ]
        == context.operation.trace.operation_id
    )

    with pytest.raises(AppError, match="tool_invocation_conflict") as conflict:
        await dispatcher.dispatch(
            name="write_tool",
            raw_arguments={"value": "different"},
            context=context,
            access=_access(),
        )
    assert conflict.value.code == "tool_invocation_conflict"
    assert capabilities.writes == 1


def test_workspace_profiles_share_one_canonical_definition_set() -> None:
    catalog = build_workspace_tool_catalog(
        ingestion=MagicMock(spec=PaperIngestionWorkflow),
        citations=MagicMock(spec=CitationWorkflow),
    )
    conversation = catalog.definitions_for(_access(CONVERSATION_TOOL_PROFILE))
    mcp = catalog.definitions_for(_access(MCP_TOOL_PROFILE))
    conversation_by_name = {tool.name: tool for tool in conversation}
    mcp_by_name = {tool.name: tool for tool in mcp}

    assert set(conversation_by_name) == set(mcp_by_name) | {"finish_tool_use"}
    assert "STOP" not in conversation_by_name
    assert "read_file" not in conversation_by_name
    assert len(mcp_by_name) == 32
    assert mcp_by_name["get_paper_citation"].execution is ToolExecutionKind.WORKFLOW
    for name, mcp_tool in mcp_by_name.items():
        conversation_tool = conversation_by_name[name]
        assert conversation_tool is mcp_tool
        assert (
            conversation_tool.input_model.model_json_schema()
            == mcp_tool.input_model.model_json_schema()
        )
