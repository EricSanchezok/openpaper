from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.database.models import ConversableType
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    conversable_type: ConversableType
    conversable_id: UUID | None = None
    title: str = Field(default="New conversation", min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_scope(self) -> ConversationCreateRequest:
        needs_id = self.conversable_type in {
            ConversableType.PAPER,
            ConversableType.PROJECT,
        }
        if needs_id != (self.conversable_id is not None):
            raise ValueError("conversable_id does not match conversable_type")
        return self


class ConversationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=240)
    pinned: bool | None = None
    archived: bool | None = None


class ConversationMoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversable_type: Literal["everything", "project"]
    conversable_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ConversationMoveRequest:
        if self.conversable_type == "project" and self.conversable_id is None:
            raise ValueError("Project conversations require conversable_id")
        if self.conversable_type == "everything" and self.conversable_id is not None:
            raise ValueError("Everything conversations cannot have conversable_id")
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
    conversable_type: ConversableType
    conversable_id: UUID | None
    scope_label: str | None
    scope_access: Literal["active", "lost"]
    pinned_at: datetime | None
    archived_at: datetime | None
    capabilities: ConversationCapabilitiesResponse


class ConversationListResponse(BaseModel):
    items: list[ConversationSummaryResponse]
    next_cursor: str | None


class ConversationDetailResponse(ConversationSummaryResponse):
    messages: list[dict[str, object]]


class ConversationAutoTitleResponse(BaseModel):
    title: str
