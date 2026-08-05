from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.modules.research.application.contracts import CitationSnapshot
from app.modules.conversations.application.contracts.answer_packet import (
    ReferenceBundle,
)
from app.modules.conversations.application.contracts.messages import ConversationTrace
from app.shared.domain import (
    JsonValue,
    WorkspacePermission,
    ordered_workspace_permissions,
)
from app.shared.domain.enums import ConversationScopeType
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class LibraryPaperContext(BaseModel):
    """All documents readable through personal or Project-based access."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["library"] = "library"


class SelectedPaperContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["selection"] = "selection"
    project_ids: list[UUID] = Field(default_factory=list, max_length=20)
    document_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @field_validator("project_ids", "document_ids", mode="before")
    @classmethod
    def normalize_ids(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return sorted({str(UUID(str(item))) for item in value})


PaperContext = Annotated[
    LibraryPaperContext | SelectedPaperContext,
    Field(discriminator="kind"),
]
OrderedWorkspacePermissions = Annotated[
    list[WorkspacePermission],
    BeforeValidator(ordered_workspace_permissions),
]


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope_type: ConversationScopeType
    scope_id: UUID | None = None
    title: str = Field(default="New conversation", min_length=1, max_length=240)
    paper_context: PaperContext | None = None
    tool_permissions: OrderedWorkspacePermissions | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ConversationCreateRequest:
        needs_id = self.scope_type in {
            ConversationScopeType.PAPER,
            ConversationScopeType.PROJECT,
        }
        if needs_id != (self.scope_id is not None):
            raise ValueError("scope_id does not match scope_type")
        return self


class ConversationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=240)
    pinned: bool | None = None
    archived: bool | None = None


class ConversationMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: Literal["global", "project"]
    scope_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ConversationMoveRequest:
        if self.scope_type == "project" and self.scope_id is None:
            raise ValueError("Project conversations require scope_id")
        if self.scope_type == "global" and self.scope_id is not None:
            raise ValueError("Global conversations cannot have scope_id")
        return self


class ConversationCapabilitiesResponse(BaseModel):
    rename: bool = True
    pin: bool = True
    move: bool
    detach: bool
    archive: bool = True
    share: bool = False
    delete: bool = True
    send: bool


class ConversationSummaryResponse(BaseModel):
    id: UUID
    title: str
    updated_at: datetime
    scope_type: ConversationScopeType
    scope_id: UUID | None
    scope_label: str | None
    scope_access: Literal["active", "lost"]
    read_only: bool
    read_only_reason: (
        Literal[
            "scope_access_lost",
            "project_deleted",
            "document_deleted",
        ]
        | None
    )
    pinned_at: datetime | None
    archived_at: datetime | None
    capabilities: ConversationCapabilitiesResponse


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]
    next_cursor: str | None


class ConversationDetailResponse(ConversationSummaryResponse):
    paper_context: PaperContext
    tool_permissions: OrderedWorkspacePermissions


class ConversationToolPermissionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permissions: OrderedWorkspacePermissions


class ConversationToolPermissionsResponse(BaseModel):
    permissions: OrderedWorkspacePermissions


class MessageResponse(BaseModel):
    id: UUID
    turn_id: UUID
    role: str
    content: str
    references: ReferenceBundle | None
    artifacts: list[CitationSnapshot] | None
    trace: ConversationTrace | None
    scope: list[dict[str, JsonValue]] | None
    sequence: int


class ConversationMessagesResponse(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None = None


class ConversationAutoTitleResponse(BaseModel):
    title: str
