"""Algorithm-neutral contracts for searching canonical papers and their text."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaperSearchScope(StrEnum):
    ALL = "all"
    LIBRARY = "library"
    PROJECTS = "projects"


class PaperSearchSort(StrEnum):
    RELEVANCE = "relevance"
    RECENT = "recent"


class PaperSearchFilters(BaseModel):
    project_id: UUID | None = None
    document_ids: list[UUID] | None = Field(default=None, max_length=500)
    published_from: datetime | None = None
    published_to: datetime | None = None

    @model_validator(mode="after")
    def validate_date_range(self) -> PaperSearchFilters:
        if (
            self.published_from is not None
            and self.published_to is not None
            and self.published_from > self.published_to
        ):
            raise ValueError("published_from must not be after published_to")
        return self


class PaperSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=1_000)
    scope: PaperSearchScope = PaperSearchScope.ALL
    filters: PaperSearchFilters = Field(default_factory=PaperSearchFilters)
    sort: PaperSearchSort = PaperSearchSort.RELEVANCE
    limit: int = Field(default=50, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1_024)

    @model_validator(mode="after")
    def validate_scope(self) -> PaperSearchRequest:
        if (
            self.filters.project_id is not None
            and self.scope is PaperSearchScope.LIBRARY
        ):
            raise ValueError("project_id cannot be used with library scope")
        return self


class PaperSearchQuery(BaseModel):
    """Internal request supplied to a replaceable search adapter."""

    query: str
    scope: PaperSearchScope
    filters: PaperSearchFilters
    sort: PaperSearchSort
    limit: int
    offset: int = Field(ge=0)
    accessible_project_document_ids: tuple[UUID, ...] = ()


class PaperSearchSnippet(BaseModel):
    text: str
    start_line: int | None = None
    end_line: int | None = None


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
    preview_url: str | None = None
    matched_fields: list[str] = Field(default_factory=list)
    snippets: list[PaperSearchSnippet] = Field(default_factory=list)


class PaperSearchResponse(BaseModel):
    items: list[PaperSearchResult]
    total: int
    next_cursor: str | None = None


class PaperSearchStats(BaseModel):
    total_papers: int
    searchable_items: int
