"""One execution path for internal Agent and inbound MCP tool calls."""

from __future__ import annotations

import hashlib
import json
from typing import Generic, Protocol, TypeVar, cast

from app.shared.application import ApplicationExecutor
from app.shared.domain import JsonValue
from app.tooling.catalog import ToolCatalog
from app.tooling.contracts import (
    ToolCallContext,
    ToolExecutionKind,
    ToolHandler,
    ToolOutcome,
)
from app.tooling.invocations import ToolInvocationGateway
from pydantic import BaseModel, TypeAdapter

CapabilitiesT = TypeVar("CapabilitiesT", bound="ToolInvocationCapabilities")
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class ToolInvocationCapabilities(Protocol):
    @property
    def tool_invocations(self) -> ToolInvocationGateway: ...


def _arguments_hash(arguments: BaseModel) -> str:
    encoded = json.dumps(
        arguments.model_dump(mode="json"),
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class ToolDispatcher(Generic[CapabilitiesT]):
    def __init__(
        self,
        *,
        catalog: ToolCatalog[CapabilitiesT],
        executor: ApplicationExecutor[CapabilitiesT],
    ) -> None:
        self._catalog = catalog
        self._executor = executor

    async def dispatch(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolCallContext,
    ) -> ToolOutcome:
        definition = self._catalog.definition(name)
        arguments = definition.input_model.model_validate(raw_arguments)
        if definition.execution is ToolExecutionKind.CONTROL:
            return ToolOutcome(payload={"completed": True}, stop=True)
        if definition.execution is ToolExecutionKind.QUERY:
            handler = cast(ToolHandler[CapabilitiesT], definition.handler)
            return self._executor.query(
                lambda capabilities: handler(
                    capabilities,
                    context,
                    arguments,
                )
            )
        if definition.execution is ToolExecutionKind.WORKFLOW:
            workflow_handler = definition.workflow_handler
            assert workflow_handler is not None
            fingerprint = _arguments_hash(arguments)
            invocation_key = f"{context.invocation_id}:{name}:{fingerprint}"
            replay = self._executor.query(
                lambda capabilities: capabilities.tool_invocations.replay(
                    actor_id=context.actor.id,
                    invocation_key=invocation_key,
                    tool_name=name,
                    arguments_hash=fingerprint,
                )
            )
            if replay is not None:
                return ToolOutcome(payload=replay, action={"replayed": True})
            outcome = await workflow_handler(
                context,
                arguments,
                invocation_key,
            )
            self._executor.command(
                lambda capabilities: capabilities.tool_invocations.complete(
                    actor_id=context.actor.id,
                    invocation_key=invocation_key,
                    source=context.source,
                    tool_name=name,
                    arguments_hash=fingerprint,
                    result=_JSON_VALUE.validate_python(outcome.payload),
                )
            )
            return outcome

        assert definition.execution is ToolExecutionKind.COMMAND
        command_handler = cast(ToolHandler[CapabilitiesT], definition.handler)
        fingerprint = _arguments_hash(arguments)
        invocation_key = f"{context.invocation_id}:{name}:{fingerprint}"

        def execute(capabilities: CapabilitiesT) -> ToolOutcome:
            replay = capabilities.tool_invocations.replay(
                actor_id=context.actor.id,
                invocation_key=invocation_key,
                tool_name=name,
                arguments_hash=fingerprint,
            )
            if replay is not None:
                return ToolOutcome(payload=replay, action={"replayed": True})
            outcome = command_handler(capabilities, context, arguments)
            capabilities.tool_invocations.complete(
                actor_id=context.actor.id,
                invocation_key=invocation_key,
                source=context.source,
                tool_name=name,
                arguments_hash=fingerprint,
                result=_JSON_VALUE.validate_python(outcome.payload),
            )
            return outcome

        return self._executor.command(execute)
