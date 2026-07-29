"""External paper-discovery use cases and replaceable ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.discovery import (
    OpenAlexCitationGraph,
    DiscoveryPaperListResponse,
    OpenAlexResponse,
    OpenAlexWork,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class AccessibleDiscoveryDocument:
    document_id: UUID
    title: str | None
    doi: str | None


class ExternalPaperCatalog(Protocol):
    async def search(self, *, query: str, page: int) -> OpenAlexResponse: ...

    async def author_works(
        self,
        *,
        author_id: str,
        page: int,
    ) -> OpenAlexResponse: ...

    async def resolve_doi(self, *, title: str) -> str | None: ...

    async def find_by_doi(self, *, doi: str) -> OpenAlexWork | None: ...

    async def citation_graph(self, *, work_id: str) -> OpenAlexCitationGraph: ...


class DiscoveryDocumentGateway(Protocol):
    def find_accessible(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessibleDiscoveryDocument | None: ...

    def set_doi(self, *, actor: Actor, document_id: UUID, doi: str) -> None: ...


class ExternalDiscoveryRateLimiter(Protocol):
    async def check(self, *, actor: Actor, client_ip: str) -> None: ...


class DiscoveryEventRecorder(Protocol):
    def record(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object],
    ) -> None: ...


class DiscoverPapers:
    def __init__(
        self,
        *,
        catalog: ExternalPaperCatalog,
        documents: DiscoveryDocumentGateway,
        rate_limiter: ExternalDiscoveryRateLimiter,
        events: DiscoveryEventRecorder,
        cursors: SignedCursorCodec,
    ) -> None:
        self._catalog = catalog
        self._documents = documents
        self._rate_limiter = rate_limiter
        self._events = events
        self._cursors = cursors

    async def search(
        self,
        *,
        actor: Actor,
        client_ip: str,
        query: str,
        cursor: str | None,
    ) -> DiscoveryPaperListResponse:
        fingerprint = f"{actor.id}:search:{query.casefold()}"
        page = (
            self._cursors.decode(cursor=cursor, fingerprint=fingerprint)
            if cursor
            else 1
        )
        await self._rate_limiter.check(actor=actor, client_ip=client_ip)
        results = await self._catalog.search(query=query, page=page)
        self._events.record(
            actor=actor,
            name="external_paper_search",
            properties={
                "page": page,
                "results_count": len(results.results),
                "total_count": results.meta.get("count", 0),
            },
        )
        return self._list_response(
            results=results,
            page=page,
            fingerprint=fingerprint,
        )

    async def author_works(
        self,
        *,
        actor: Actor,
        client_ip: str,
        author_id: str,
        cursor: str | None,
    ) -> DiscoveryPaperListResponse:
        fingerprint = f"{actor.id}:author:{author_id}"
        page = (
            self._cursors.decode(cursor=cursor, fingerprint=fingerprint)
            if cursor
            else 1
        )
        await self._rate_limiter.check(actor=actor, client_ip=client_ip)
        results = await self._catalog.author_works(author_id=author_id, page=page)
        self._events.record(
            actor=actor,
            name="author_works_view",
            properties={
                "page": page,
                "results_count": len(results.results),
                "total_count": results.meta.get("count", 0),
            },
        )
        return self._list_response(
            results=results,
            page=page,
            fingerprint=fingerprint,
        )

    def _list_response(
        self,
        *,
        results: OpenAlexResponse,
        page: int,
        fingerprint: str,
    ) -> DiscoveryPaperListResponse:
        count_value = results.meta.get("count", 0)
        per_page_value = results.meta.get("per_page", len(results.results))
        count = count_value if isinstance(count_value, int) else 0
        per_page = (
            per_page_value
            if isinstance(per_page_value, int) and per_page_value > 0
            else len(results.results) or 1
        )
        has_more = page * per_page < count
        return DiscoveryPaperListResponse(
            items=results.results,
            next_cursor=(
                self._cursors.encode(
                    fingerprint=fingerprint,
                    offset=page + 1,
                )
                if has_more
                else None
            ),
        )

    async def match(
        self,
        *,
        actor: Actor,
        client_ip: str,
        doi: str | None,
        document_id: UUID | None,
    ) -> OpenAlexCitationGraph:
        await self._rate_limiter.check(actor=actor, client_ip=client_ip)
        if doi is None and document_id is None:
            raise AppError(
                code="citation_graph_source_required",
                message="Either doi or document_id must be provided",
                kind=FailureKind.INVALID_ARGUMENT,
            )

        document: AccessibleDiscoveryDocument | None = None
        if document_id is not None:
            document = self._documents.find_accessible(
                actor=actor,
                document_id=document_id,
            )
            if document is None:
                raise AppError(
                    code="paper_not_found",
                    message="Paper not found",
                    kind=FailureKind.NOT_FOUND,
                )
            if doi is None:
                doi = document.doi
                if doi is None and document.title:
                    doi = await self._catalog.resolve_doi(title=document.title)

        if doi is None:
            raise AppError(
                code="paper_doi_unavailable",
                message="A DOI could not be determined for this paper",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        work = await self._catalog.find_by_doi(doi=doi)
        if work is None:
            raise AppError(
                code="openalex_paper_not_found",
                message="OpenAlex could not find a paper for this DOI",
                kind=FailureKind.NOT_FOUND,
            )
        if document is not None and document.doi != doi:
            self._documents.set_doi(
                actor=actor,
                document_id=document.document_id,
                doi=doi,
            )

        graph = await self._catalog.citation_graph(work_id=work.id)
        self._events.record(
            actor=actor,
            name="citation_graph_view",
            properties={
                "cited_by_count": graph.cited_by.meta.get("count", 0),
                "cites_count": graph.cites.meta.get("count", 0),
            },
        )
        return graph
