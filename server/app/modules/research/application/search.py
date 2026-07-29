"""Independent search capability for highlights and their comments."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.shared.application import Actor, SignedCursorCodec
from pydantic import BaseModel, ConfigDict, Field

RESEARCH_SEARCH_REVISION = "research-search:1"


class ResearchSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=2, max_length=1_000)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=1_024)


class ResearchSearchQuery(BaseModel):
    query: str
    limit: int
    offset: int = Field(ge=0)


class ResearchSearchComment(BaseModel):
    id: UUID
    content: str
    role: str
    created_at: datetime


class ResearchSearchResult(BaseModel):
    id: UUID
    document_id: UUID
    document_title: str | None
    quote_text: str
    page_number: int | None
    start_offset: int | None
    end_offset: int | None
    role: str
    created_at: datetime
    matching_comments: list[ResearchSearchComment]


class ResearchSearchResponse(BaseModel):
    items: list[ResearchSearchResult]
    total: int
    next_cursor: str | None = None


class ResearchSearchPort(Protocol):
    def search(
        self,
        *,
        actor: Actor,
        request: ResearchSearchQuery,
    ) -> ResearchSearchResponse: ...


class SearchResearch:
    def __init__(self, search: ResearchSearchPort, cursors: SignedCursorCodec) -> None:
        self._search = search
        self._cursors = cursors

    def __call__(
        self,
        *,
        actor: Actor,
        request: ResearchSearchRequest,
    ) -> ResearchSearchResponse:
        normalized = request.model_copy(update={"query": request.query.strip()})
        fingerprint = json.dumps(
            normalized.model_dump(mode="json", exclude={"cursor"}),
            separators=(",", ":"),
            sort_keys=True,
        )
        offset = (
            self._cursors.decode(
                cursor=request.cursor,
                fingerprint=fingerprint,
            )
            if request.cursor
            else 0
        )
        response = self._search.search(
            actor=actor,
            request=ResearchSearchQuery(
                query=normalized.query,
                limit=normalized.limit,
                offset=offset,
            ),
        )
        consumed = offset + len(response.items)
        next_cursor = (
            self._cursors.encode(fingerprint=fingerprint, offset=consumed)
            if consumed < response.total
            else None
        )
        return response.model_copy(update={"next_cursor": next_cursor})


def build_research_search_cursor(secret: str) -> SignedCursorCodec:
    return SignedCursorCodec(
        secret,
        revision=RESEARCH_SEARCH_REVISION,
        error_code="research_search_cursor_expired",
    )
