"""One execution path for internal Agent and inbound MCP tool calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Generic, Protocol, TypeVar, cast

from app.shared.application import ApplicationExecutor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.tooling.catalog import ToolCatalog
from app.tooling.contracts import (
    ToolCallContext,
    ToolAccess,
    ToolExecutionKind,
    ToolHandler,
    ToolOutcome,
)
from app.tooling.invocations import ToolInvocationGateway
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

CapabilitiesT = TypeVar("CapabilitiesT", bound="ToolInvocationCapabilities")
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class _PersistedToolOutcome(BaseModel):
    payload: JsonValue
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)
    action: dict[str, JsonValue] | None = None
    stop: bool = False


def _persisted_outcome(outcome: ToolOutcome) -> JsonValue:
    return _JSON_VALUE.validate_python(
        _PersistedToolOutcome(
            payload=outcome.payload,
            evidence=outcome.evidence,
            artifacts=outcome.artifacts,
            action=outcome.action,
            stop=outcome.stop,
        ).model_dump(mode="json")
    )


def _restore_outcome(value: JsonValue) -> ToolOutcome:
    try:
        persisted = _PersistedToolOutcome.model_validate(value)
    except ValidationError as exc:
        raise AppError(
            kind=FailureKind.DEPENDENCY_FAILURE,
            code="tool_invocation_result_invalid",
            message="Stored tool invocation result is invalid",
        ) from exc
    return ToolOutcome(
        payload=persisted.payload,
        evidence=persisted.evidence,
        artifacts=persisted.artifacts,
        action=persisted.action,
        stop=persisted.stop,
    )


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
        access: ToolAccess,
    ) -> ToolOutcome:
        try:
            definition = self._catalog.definition_for(access, name)
        except KeyError as exc:
            raise AppError(
                kind=FailureKind.NOT_FOUND,
                code="tool_not_found",
                message="Tool not found",
            ) from exc
        try:
            arguments = definition.input_model.model_validate(raw_arguments)
        except ValidationError as exc:
            raise AppError(
                kind=FailureKind.INVALID_ARGUMENT,
                code="tool_arguments_invalid",
                message="Tool arguments are invalid",
                details={
                    "errors": exc.errors(
                        include_url=False,
                        include_context=False,
                    )
                },
            ) from exc
        if definition.execution is ToolExecutionKind.CONTROL:
            return ToolOutcome(payload={"completed": True}, stop=True)
        if definition.execution is ToolExecutionKind.QUERY:
            handler = cast(ToolHandler[CapabilitiesT], definition.handler)
            return await asyncio.to_thread(
                self._executor.query,
                lambda capabilities: handler(capabilities, context, arguments),
            )
        if definition.execution is ToolExecutionKind.WORKFLOW:
            workflow_handler = definition.workflow_handler
            assert workflow_handler is not None
            fingerprint = _arguments_hash(arguments)
            invocation_key = f"{context.invocation_id}:{name}"
            replay = await asyncio.to_thread(
                self._executor.query,
                lambda capabilities: capabilities.tool_invocations.replay(
                    actor_id=context.actor.id,
                    invocation_key=invocation_key,
                    tool_name=name,
                    arguments_hash=fingerprint,
                ),
            )
            if replay is not None:
                return _restore_outcome(replay)
            outcome = await workflow_handler(
                context,
                arguments,
                invocation_key,
            )
            await asyncio.to_thread(
                self._executor.command,
                lambda capabilities: capabilities.tool_invocations.complete(
                    actor_id=context.actor.id,
                    invocation_key=invocation_key,
                    source=context.source,
                    tool_name=name,
                    arguments_hash=fingerprint,
                    result=_persisted_outcome(outcome),
                ),
            )
            return outcome

        assert definition.execution is ToolExecutionKind.COMMAND
        command_handler = cast(ToolHandler[CapabilitiesT], definition.handler)
        fingerprint = _arguments_hash(arguments)
        invocation_key = f"{context.invocation_id}:{name}"

        def execute(capabilities: CapabilitiesT) -> ToolOutcome:
            replay = capabilities.tool_invocations.replay(
                actor_id=context.actor.id,
                invocation_key=invocation_key,
                tool_name=name,
                arguments_hash=fingerprint,
            )
            if replay is not None:
                return _restore_outcome(replay)
            outcome = command_handler(capabilities, context, arguments)
            capabilities.tool_invocations.complete(
                actor_id=context.actor.id,
                invocation_key=invocation_key,
                source=context.source,
                tool_name=name,
                arguments_hash=fingerprint,
                result=_persisted_outcome(outcome),
            )
            return outcome

        return await asyncio.to_thread(self._executor.command, execute)
