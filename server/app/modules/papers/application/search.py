"""Replaceable application boundary for private paper search."""

from __future__ import annotations

from typing import Protocol

from app.modules.papers.application.contracts.search import (
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchStats,
)
from app.shared.application import Actor


class PaperSearchPort(Protocol):
    """Algorithm-neutral search capability used by every transport."""

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchRequest,
    ) -> PaperSearchResponse: ...

    def stats(self, *, actor: Actor) -> PaperSearchStats: ...


class SearchPapers:
    def __init__(self, search: PaperSearchPort) -> None:
        self._search = search

    def __call__(
        self,
        *,
        actor: Actor,
        request: PaperSearchRequest,
    ) -> PaperSearchResponse:
        normalized = request.model_copy(update={"query": request.query.strip()})
        return self._search.search(actor=actor, request=normalized)


class GetPaperSearchStats:
    def __init__(self, search: PaperSearchPort) -> None:
        self._search = search

    def __call__(self, *, actor: Actor) -> PaperSearchStats:
        return self._search.stats(actor=actor)
