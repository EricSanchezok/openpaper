"""OpenAlex, quota, persistence, and telemetry adapters for discovery."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.database.telemetry import track_event
from app.helpers.ai_limits import AILimitExceeded, enforce_rate_limit
from app.helpers.paper_search import (
    construct_citation_graph,
    get_doi,
    get_work_by_doi,
    search_open_alex,
)
from app.modules.papers.application.contracts.discovery import (
    OpenAlexCitationGraph,
    OpenAlexFilter,
    OpenAlexResponse,
    OpenAlexWork,
)
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.application.discovery import AccessibleDiscoveryDocument
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor
from app.shared.domain import AppError
from sqlalchemy.orm import Session


class OpenAlexPaperCatalog:
    async def search(self, *, query: str, page: int) -> OpenAlexResponse:
        return await asyncio.to_thread(search_open_alex, query, None, page)

    async def author_works(
        self,
        *,
        author_id: str,
        page: int,
    ) -> OpenAlexResponse:
        return await asyncio.to_thread(
            search_open_alex,
            None,
            OpenAlexFilter(authors=[author_id]),
            page,
        )

    async def resolve_doi(self, *, title: str) -> str | None:
        return await asyncio.to_thread(get_doi, title)

    async def find_by_doi(self, *, doi: str) -> OpenAlexWork | None:
        return await asyncio.to_thread(get_work_by_doi, doi)

    async def citation_graph(self, *, work_id: str) -> OpenAlexCitationGraph:
        return await asyncio.to_thread(construct_citation_graph, work_id)


class SqlDiscoveryDocumentGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_accessible(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessibleDiscoveryDocument | None:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        if document is None:
            return None
        return AccessibleDiscoveryDocument(
            document_id=document.id,
            title=document.title,
            doi=document.doi,
        )

    def set_doi(self, *, actor: Actor, document_id: UUID, doi: str) -> None:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        if document is None:
            raise RuntimeError("accessible_document_disappeared")
        document_repository.update_canonical(
            self._db,
            document=document,
            update=DocumentUpdate(doi=doi),
        )


class AiExternalDiscoveryRateLimiter:
    async def check(self, *, actor: Actor, client_ip: str) -> None:
        try:
            await enforce_rate_limit(
                user_id=actor.id,
                ip_address=client_ip,
                feature="external_search",
            )
        except AILimitExceeded as exc:
            raise AppError(
                code=exc.code,
                message="External search rate limit exceeded",
                status_code=429,
            ) from None


class PostHogDiscoveryEventRecorder:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object],
    ) -> None:
        track_event(
            name,
            user_id=str(actor.id),
            properties=properties,
            db=self._db,
        )
