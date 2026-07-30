"""Replaceable application boundary for private paper search."""

from __future__ import annotations

import json
from typing import Protocol
from app.modules.papers.application.contracts.search import (
    PaperCollection,
    PaperSearchQuery,
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchStats,
)
from app.shared.application import Actor, SignedCursorCodec

SEARCH_CURSOR_REVISION = "paper-search:2"


class SearchCursorCodec(SignedCursorCodec):
    def __init__(self, secret: str) -> None:
        super().__init__(
            secret,
            revision=SEARCH_CURSOR_REVISION,
            error_code="search_cursor_expired",
        )


class PaperSearchPort(Protocol):
    """Algorithm-neutral search capability used by every transport."""

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchResponse: ...

    def stats(
        self,
        *,
        actor: Actor,
    ) -> PaperSearchStats: ...


class PaperSearchAccessPort(Protocol):
    def require_collection_access(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
    ) -> None: ...


class SearchPapers:
    def __init__(
        self,
        search: PaperSearchPort,
        cursors: SearchCursorCodec,
        access: PaperSearchAccessPort,
    ) -> None:
        self._search = search
        self._cursors = cursors
        self._access = access

    def __call__(
        self,
        *,
        actor: Actor,
        request: PaperSearchRequest,
    ) -> PaperSearchResponse:
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
        self._access.require_collection_access(
            actor=actor,
            collection=normalized.collection,
        )
        response = self._search.search(
            actor=actor,
            request=PaperSearchQuery(
                query=normalized.query,
                collection=normalized.collection,
                filters=normalized.filters,
                sort=normalized.sort,
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


class GetPaperSearchStats:
    def __init__(
        self,
        search: PaperSearchPort,
    ) -> None:
        self._search = search

    def __call__(self, *, actor: Actor) -> PaperSearchStats:
        return self._search.stats(
            actor=actor,
        )
