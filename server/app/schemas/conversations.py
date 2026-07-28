from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.database.models import ConversationScopeType, JsonValue, Message
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    scope_type: ConversationScopeType
    scope_id: UUID | None = None
    title: str = Field(default="New conversation", min_length=1, max_length=240)

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
    pass


class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    references: dict[str, JsonValue] | None
    artifacts: list[dict[str, JsonValue]] | None
    trace: dict[str, JsonValue] | None
    scope: list[dict[str, JsonValue]] | None
    sequence: int


class ConversationMessagesResponse(BaseModel):
    items: list[MessageResponse]
    page: int
    page_size: int


class ConversationAutoTitleResponse(BaseModel):
    title: str


def serialize_messages(messages: list[Message]) -> list[MessageResponse]:
    return [
        MessageResponse.model_validate(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "references": message.references,
                "artifacts": [
                    item.citation.snapshot
                    for item in message.research_items
                    if item.citation is not None
                ]
                or None,
                "trace": message.trace,
                "scope": message.scope,
                "sequence": message.sequence,
            }
        )
        for message in messages
    ]
