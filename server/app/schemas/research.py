from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.database.models import ResearchItemKind, ResearchScopeType
from app.shared.infrastructure.persistence import JsonValue
from app.schemas.citation import CitationData, CitationMethod
from app.schemas.responses import ResponseCitation
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResearchCreatorResponse(BaseModel):
    id: int | None
    display_name: str | None


class AnnotationCommentResponse(BaseModel):
    id: UUID
    thread_id: UUID
    content: str
    role: str
    created_by: ResearchCreatorResponse
    created_at: datetime
    updated_at: datetime
    can_edit: bool
    can_delete: bool


class HighlightThreadContent(BaseModel):
    quote_text: str
    page_number: int | None
    start_offset: int | None
    end_offset: int | None
    position: dict[str, JsonValue] | None
    color: str
    role: str
    comments: list[AnnotationCommentResponse]


class CitationSnapshot(BaseModel):
    """Immutable, validated citation card emitted by the evidence pipeline."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["citation"]
    document_id: str = Field(min_length=1, max_length=100)
    preferred_style: str = Field(min_length=1, max_length=100)
    style_display: str = Field(min_length=1, max_length=200)
    data: CitationData
    method: CitationMethod
    missing_fields: list[str] = Field(default_factory=list, max_length=100)
    confidence: float | None = Field(default=None, ge=0, le=1)


class CitationContent(BaseModel):
    snapshot: CitationSnapshot


class AudioOverviewContent(BaseModel):
    title: str | None
    transcript: str
    citations: list[ResponseCitation]
    audio_url: str
    voice_id: str
    model_version: str


class DataTableContent(BaseModel):
    title: str | None
    columns: list[str]
    rows: list[dict[str, JsonValue]]
    citations: list[dict[str, JsonValue]]
    row_failures: list[str]


class ResearchItemCapabilities(BaseModel):
    share: bool
    edit: bool
    delete: bool


class ResearchItemResponse(BaseModel):
    id: UUID
    kind: ResearchItemKind
    scope_type: ResearchScopeType
    scope_id: UUID | None
    is_shared: bool
    created_by: ResearchCreatorResponse
    created_at: datetime
    updated_at: datetime
    capabilities: ResearchItemCapabilities
    highlight_thread: HighlightThreadContent | None = None
    citation: CitationContent | None = None
    audio_overview: AudioOverviewContent | None = None
    data_table: DataTableContent | None = None

    @model_validator(mode="after")
    def validate_content(self) -> ResearchItemResponse:
        populated = sum(
            value is not None
            for value in (
                self.highlight_thread,
                self.citation,
                self.audio_overview,
                self.data_table,
            )
        )
        if populated != 1:
            raise ValueError("research item must contain exactly one typed payload")
        return self


class ResearchItemListResponse(BaseModel):
    items: list[ResearchItemResponse]


class ResearchVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shared: bool


class CreateHighlightThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    quote_text: str = Field(min_length=1, max_length=100_000)
    page_number: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    position: dict[str, JsonValue] | None = None
    color: str = Field(default="blue", min_length=1, max_length=32)
    shared: bool = True

    @model_validator(mode="after")
    def validate_offsets(self) -> CreateHighlightThreadRequest:
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset must not precede start_offset")
        return self


class UpdateHighlightThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    quote_text: str | None = Field(default=None, min_length=1, max_length=100_000)
    page_number: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    position: dict[str, JsonValue] | None = None
    color: str | None = Field(default=None, min_length=1, max_length=32)
    shared: bool | None = None


class DeleteHighlightThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_delete_replies: bool = False


class CreateAnnotationCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=100_000)


class UpdateAnnotationCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=100_000)


class DeleteResearchItemResponse(BaseModel):
    deleted: Literal[True] = True
