"""Stable contracts for searching papers accessible to an actor."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PaperSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1_000)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class HighlightSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    raw_text: str
    start_offset: int | None
    end_offset: int | None
    page_number: int | None
    role: str
    created_at: datetime


class AnnotationSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    role: str
    created_at: datetime
    highlight: HighlightSearchResult


class PaperSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: UUID
    title: str | None
    authors: list[str] | None
    abstract: str | None
    status: str
    publish_date: datetime | None
    created_at: datetime
    last_accessed_at: datetime
    highlights: list[HighlightSearchResult]
    annotations: list[AnnotationSearchResult]
    preview_url: str | None = None


class PaperSearchResponse(BaseModel):
    papers: list[PaperSearchResult]
    total_papers: int
    total_highlights: int
    total_annotations: int


class PaperSearchStats(BaseModel):
    total_papers: int
    total_highlights: int
    total_annotations: int
    searchable_items: int
