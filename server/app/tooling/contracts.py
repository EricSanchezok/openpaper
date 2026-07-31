"""Transport-neutral contracts for model-visible tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Literal, TypeAlias, TypeVar
from uuid import UUID

from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import Actor, OperationContext
from app.shared.domain import (
    JsonValue,
    WorkspacePermission,
    normalize_workspace_permissions,
)
from pydantic import BaseModel

CapabilitiesT = TypeVar("CapabilitiesT")


class ToolExecutionKind(StrEnum):
    QUERY = "query"
    COMMAND = "command"
    WORKFLOW = "workflow"
    CONTROL = "control"


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentSourceCandidate:
    kind: Literal["document"] = "document"
    document_id: UUID
    excerpt: str
    title: str | None = None
    authors: tuple[str, ...] = ()
    locator: dict[str, JsonValue] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalSourceCandidate:
    kind: Literal["external"] = "external"
    url: str
    excerpt: str | None = None
    title: str | None = None
    origin: dict[str, JsonValue] | None = None


ToolSourceCandidate: TypeAlias = DocumentSourceCandidate | ExternalSourceCandidate


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    actor: Actor
    operation: OperationContext
    paper_collection: PaperCollection
    anchor_document_id: UUID | None
    invocation_id: str
    client_ip: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.invocation_id, str)
            or not self.invocation_id
            or len(self.invocation_id) > 1024
        ):
            raise ValueError("tool invocation_id must be a bounded non-empty string")
        if (
            not isinstance(self.client_ip, str)
            or not self.client_ip
            or self.client_ip != self.client_ip.strip()
            or len(self.client_ip) > 64
        ):
            raise ValueError("tool client_ip must be a bounded normalized string")


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    payload: JsonValue
    sources: tuple[ToolSourceCandidate, ...] = ()
    artifacts: list[dict[str, JsonValue]] = field(default_factory=list)
    action: dict[str, JsonValue] | None = None
    stop: bool = False


ToolHandler = Callable[[CapabilitiesT, ToolExecutionContext, BaseModel], ToolOutcome]
WorkflowToolHandler = Callable[
    [ToolExecutionContext, BaseModel, str],
    Awaitable[ToolOutcome],
]


@dataclass(frozen=True, slots=True)
class ToolAccess:
    profile_name: str
    permissions: frozenset[WorkspacePermission]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "permissions",
            normalize_workspace_permissions(self.permissions),
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolDefinition(Generic[CapabilitiesT]):
    name: str
    description: str
    input_model: type[BaseModel]
    execution: ToolExecutionKind
    required_permission: WorkspacePermission | None
    handler: ToolHandler[CapabilitiesT] | None = None
    workflow_handler: WorkflowToolHandler | None = None

    def __post_init__(self) -> None:
        if (
            not self.name
            or self.name.lower() != self.name
            or not self.name.isidentifier()
        ):
            raise ValueError("tool names must be non-empty lowercase identifiers")
        if self.execution is ToolExecutionKind.CONTROL:
            if self.required_permission is not None:
                raise ValueError("control tools cannot require workspace permission")
            if self.handler is not None or self.workflow_handler is not None:
                raise ValueError("control tools cannot define handlers")
            return
        if self.required_permission is None:
            raise ValueError("business tools require one workspace permission")
        if self.execution is ToolExecutionKind.WORKFLOW:
            if self.workflow_handler is None or self.handler is not None:
                raise ValueError("workflow tools require exactly one workflow handler")
            return
        if self.handler is None or self.workflow_handler is not None:
            raise ValueError("query and command tools require exactly one handler")
