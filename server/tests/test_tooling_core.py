from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from uuid import uuid4

import pytest
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.tooling import (
    ToolCallContext,
    ToolCatalog,
    ToolDefinition,
    ToolDispatcher,
    ToolExecutionKind,
    ToolOutcome,
    ToolProfile,
)
from app.tooling.invocations import ToolInvocationGateway
from pydantic import BaseModel

ResultT = TypeVar("ResultT")


class Arguments(BaseModel):
    value: str


class MemoryInvocationGateway(ToolInvocationGateway):
    def __init__(self) -> None:
        self.items: dict[tuple[int, str], tuple[str, str, JsonValue]] = {}

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
        invocation_key: str,
        source: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None:
        del source
        self.items[(actor_id, invocation_key)] = (
            tool_name,
            arguments_hash,
            result,
        )


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


def _context() -> ToolCallContext:
    return ToolCallContext(
        actor=Actor(
            id=1,
            email="user@example.com",
            status="active",
            email_verified=True,
        ),
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        source="conversation",
        invocation_id="turn-1",
        client_ip="test",
        conversation_id=uuid4(),
        turn_id=uuid4(),
    )


def test_profiles_are_independent_and_validate_references() -> None:
    query = ToolDefinition[Capabilities](
        name="query_tool",
        description="query",
        input_model=Arguments,
        execution=ToolExecutionKind.QUERY,
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

    assert catalog.definitions_for("conversation") == []
    assert [item.name for item in catalog.definitions_for("mcp")] == ["query_tool"]
    with pytest.raises(ValueError, match="missing tools"):
        ToolCatalog(
            [query],
            [ToolProfile(name="broken", tool_names=frozenset({"missing"}))],
        )


@pytest.mark.asyncio
async def test_command_dispatch_is_persistently_replayed() -> None:
    def write(
        capabilities: Capabilities,
        context: ToolCallContext,
        arguments: BaseModel,
    ) -> ToolOutcome:
        del context
        parsed = Arguments.model_validate(arguments)
        capabilities.writes += 1
        return ToolOutcome(
            payload={"value": parsed.value},
            action={"kind": "write"},
        )

    definition = ToolDefinition[Capabilities](
        name="write_tool",
        description="write",
        input_model=Arguments,
        execution=ToolExecutionKind.COMMAND,
        handler=write,
    )
    catalog = ToolCatalog(
        [definition],
        [ToolProfile(name="conversation", tool_names=frozenset({"write_tool"}))],
    )
    capabilities = Capabilities(MemoryInvocationGateway())
    executor = Executor(capabilities)
    dispatcher = ToolDispatcher(catalog=catalog, executor=executor)

    first = await dispatcher.dispatch(
        name="write_tool",
        raw_arguments={"value": "same"},
        context=_context(),
    )
    second = await dispatcher.dispatch(
        name="write_tool",
        raw_arguments={"value": "same"},
        context=_context(),
    )

    assert first.payload == {"value": "same"}
    assert second.payload == {"value": "same"}
    assert second.action == {"replayed": True}
    assert capabilities.writes == 1
    assert executor.commands == 2
