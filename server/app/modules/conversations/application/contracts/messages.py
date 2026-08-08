import uuid
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.shared.domain import JsonValue
from app.shared.domain.enums import ReasoningLevel
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class ConversationStreamStartEvent(BaseModel):
    type: Literal["start"] = "start"
    conversation_id: uuid.UUID
    turn_id: uuid.UUID


class ConversationActivity(BaseModel):
    """One sanitized, user-inspectable tool lifecycle entry."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    category: Literal["search", "read", "workspace_action", "connector"]
    state: Literal["running", "succeeded", "failed"]
    tool_name: str = Field(min_length=1, max_length=128)
    subject: str | None = Field(default=None, max_length=240)
    connector_name: str | None = Field(default=None, max_length=80)
    source_count: int | None = Field(default=None, ge=0)
    artifact_count: int | None = Field(default=None, ge=0)


class ConversationCitationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_count: int = Field(ge=0)
    annotation_count: int = Field(ge=0)
    rejected_source_count: int = Field(ge=0)


class ConversationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activities: list[ConversationActivity] = Field(default_factory=list)
    citation_summary: ConversationCitationSummary | None = None


class ConversationStreamActivityEvent(BaseModel):
    type: Literal["activity"] = "activity"
    activity: ConversationActivity


class ConversationStreamContentDeltaEvent(BaseModel):
    type: Literal["content_delta"] = "content_delta"
    delta: str


class ConversationStreamReferencesEvent(BaseModel):
    type: Literal["references"] = "references"
    references: dict[str, JsonValue]


class ConversationStreamCompleteEvent(BaseModel):
    type: Literal["complete"] = "complete"
    turn_id: uuid.UUID
    trace: ConversationTrace | None = None
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)


class ConversationStreamErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    error: dict[str, JsonValue]


ConversationStreamEvent = Annotated[
    ConversationStreamStartEvent
    | ConversationStreamActivityEvent
    | ConversationStreamContentDeltaEvent
    | ConversationStreamReferencesEvent
    | ConversationStreamCompleteEvent
    | ConversationStreamErrorEvent,
    Field(discriminator="type"),
]


class ConversationStreamEventSchema(RootModel[ConversationStreamEvent]):
    """Public schema for the JSON payload carried by each SSE event."""


class ConversationMessageRequest(BaseModel):
    """One stable message contract for every conversation scope."""

    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    user_query: str = Field(min_length=1, max_length=20_000)
    locale: Literal["en", "zh-CN"]
    time_zone: str = Field(min_length=1, max_length=100)
    user_references: list[str] | None = Field(default=None, max_length=50)
    reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD
    mentioned_highlight_ids: list[str] | None = Field(default=None, max_length=50)

    @field_validator("mentioned_highlight_ids")
    @classmethod
    def validate_mentioned_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            for item in value:
                uuid.UUID(item)
        return value

    @field_validator("user_references")
    @classmethod
    def validate_references(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(len(item) > 5_000 for item in value):
            raise ValueError("Reference text exceeds maximum length")
        return value

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("time_zone must be a valid IANA time zone") from exc
        return value
