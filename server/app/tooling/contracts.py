"""Transport-neutral contracts for model-visible tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import Actor
from app.shared.domain import JsonValue
from pydantic import BaseModel

CapabilitiesT = TypeVar("CapabilitiesT")


class ToolExecutionKind(StrEnum):
    QUERY = "query"
    COMMAND = "command"
    WORKFLOW = "workflow"
    CONTROL = "control"


@dataclass(frozen=True, slots=True)
class ToolCallContext:
    actor: Actor
    paper_collection: PaperCollection
    anchor_document_id: UUID | None
    source: str
    invocation_id: str
    client_ip: str
    conversation_id: UUID | None = None
    turn_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    payload: JsonValue
    evidence: dict[str, list[str]] = field(default_factory=dict)
    artifacts: list[dict[str, JsonValue]] = field(default_factory=list)
    action: dict[str, JsonValue] | None = None
    stop: bool = False


ToolHandler = Callable[[CapabilitiesT, ToolCallContext, BaseModel], ToolOutcome]
WorkflowToolHandler = Callable[
    [ToolCallContext, BaseModel, str],
    Awaitable[ToolOutcome],
]


@dataclass(frozen=True, slots=True)
class ToolDefinition(Generic[CapabilitiesT]):
    name: str
    description: str
    input_model: type[BaseModel]
    execution: ToolExecutionKind
    handler: ToolHandler[CapabilitiesT] | None = None
    workflow_handler: WorkflowToolHandler | None = None

    def __post_init__(self) -> None:
        if not self.name or self.name.lower() != self.name:
            raise ValueError("tool names must be non-empty lowercase identifiers")
        if self.execution is ToolExecutionKind.CONTROL:
            if self.handler is not None or self.workflow_handler is not None:
                raise ValueError("control tools cannot define handlers")
            return
        if self.execution is ToolExecutionKind.WORKFLOW:
            if self.workflow_handler is None or self.handler is not None:
                raise ValueError("workflow tools require exactly one workflow handler")
            return
        if self.handler is None or self.workflow_handler is not None:
            raise ValueError("query and command tools require exactly one handler")
