"""Replaceable application boundary for private paper search."""

from __future__ import annotations

import json
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.search import (
    PaperSearchQuery,
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchScope,
    PaperSearchStats,
)
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor, SignedCursorCodec

SEARCH_CURSOR_REVISION = "paper-search:1"


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
        accessible_project_document_ids: tuple[UUID, ...],
    ) -> PaperSearchStats: ...


class SearchPapers:
    def __init__(
        self,
        search: PaperSearchPort,
        cursors: SearchCursorCodec,
        project_documents: ListAccessibleProjectDocuments,
    ) -> None:
        self._search = search
        self._cursors = cursors
        self._project_documents = project_documents

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
        project_document_ids = (
            self._project_documents(
                actor=actor,
                project_id=normalized.filters.project_id,
            )
            if normalized.scope is not PaperSearchScope.LIBRARY
            else ()
        )
        response = self._search.search(
            actor=actor,
            request=PaperSearchQuery(
                query=normalized.query,
                scope=normalized.scope,
                filters=normalized.filters,
                sort=normalized.sort,
                limit=normalized.limit,
                offset=offset,
                accessible_project_document_ids=project_document_ids,
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
        project_documents: ListAccessibleProjectDocuments,
    ) -> None:
        self._search = search
        self._project_documents = project_documents

    def __call__(self, *, actor: Actor) -> PaperSearchStats:
        return self._search.stats(
            actor=actor,
            accessible_project_document_ids=self._project_documents(actor=actor),
        )
