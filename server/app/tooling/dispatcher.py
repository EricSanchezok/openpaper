"""One execution path for internal Agent and inbound MCP tool calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
from time import monotonic
from typing import Generic, Protocol, TypeVar, cast

from app.shared.application import ApplicationExecutor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.tooling.catalog import ToolCatalog
from app.tooling.contracts import (
    ToolExecutionContext,
    ToolAccess,
    ToolExecutionKind,
    ToolHandler,
    ToolOutcome,
    ToolSourceCandidate,
)
from app.tooling.invocations import ToolInvocationGateway
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from scholens_observability import add_counter, instrumented_span, record_histogram

CapabilitiesT = TypeVar("CapabilitiesT", bound="ToolInvocationCapabilities")
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class _PersistedToolOutcome(BaseModel):
    payload: JsonValue
    sources: tuple[ToolSourceCandidate, ...] = ()
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)
    action: dict[str, JsonValue] | None = None


def _persisted_outcome(outcome: ToolOutcome) -> JsonValue:
    return _JSON_VALUE.validate_python(
        _PersistedToolOutcome(
            payload=outcome.payload,
            sources=outcome.sources,
            artifacts=outcome.artifacts,
            action=outcome.action,
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
        sources=persisted.sources,
        artifacts=persisted.artifacts,
        action=persisted.action,
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
        context: ToolExecutionContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        started = monotonic()
        status = "success"
        execution = "unknown"
        try:
            return await self._dispatch(
                name=name,
                raw_arguments=raw_arguments,
                context=context,
                access=access,
            )
        except BaseException:
            status = "failure"
            raise
        finally:
            try:
                execution = self._catalog.definition_for(access, name).execution.value
            except KeyError:
                pass
            attributes = {
                "tool": name,
                "execution": execution,
                "status": status,
                "source": "local",
            }
            add_counter("scholens.tool.calls", attributes=attributes)
            record_histogram(
                "scholens.tool.duration",
                (monotonic() - started) * 1000,
                attributes=attributes,
            )

    async def _dispatch(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolExecutionContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        with instrumented_span(
            "tool.dispatch",
            attributes={"tool.name": name, "tool.source": "local"},
        ):
            return await self._dispatch_in_span(
                name=name,
                raw_arguments=raw_arguments,
                context=context,
                access=access,
            )

    async def _dispatch_in_span(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolExecutionContext,
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
                        include_input=False,
                    )
                },
            ) from exc
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
                    operation_id=context.operation.trace.operation_id,
                    invocation_key=invocation_key,
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
                operation_id=context.operation.trace.operation_id,
                invocation_key=invocation_key,
                tool_name=name,
                arguments_hash=fingerprint,
                result=_persisted_outcome(outcome),
            )
            return outcome

        return await asyncio.to_thread(self._executor.command, execute)
