"""Protocol-neutral MCP adapter over the existing paper application handlers.

The formal MCP server is intentionally deferred. This adapter fixes the
boundary now: a future server only validates MCP arguments and delegates here;
it never calls Scholens HTTP endpoints or repositories.
"""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import create_paper_ingestion_workflow
from app.modules.papers.application.contracts.search import (
    PaperSearchRequest,
    PaperSearchResponse,
)
from app.modules.papers.application.contracts.documents import DocumentFileUrlResponse
from app.modules.papers.application.contracts.citation import CitationResult
from app.modules.papers.application.contracts.uploads import UploadAcceptedResponse
from app.shared.application import Actor, ApplicationExecutor


class McpPaperTools:
    def __init__(
        self,
        *,
        actor: Actor,
        executor: ApplicationExecutor[ApplicationCapabilities],
    ) -> None:
        self._actor = actor
        self._executor = executor

    def read_document(
        self,
        *,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> dict[str, object]:
        paper = self._executor.query(
            lambda capabilities: capabilities.paper_content.read(
                actor=self._actor,
                document_id=document_id,
                project_id=project_id,
            )
        )
        return {
            "document_id": str(paper.document_id),
            "title": paper.title,
            "abstract": paper.abstract,
            "content": paper.raw_content,
        }

    def search_papers(self, request: PaperSearchRequest) -> PaperSearchResponse:
        return self._executor.query(
            lambda capabilities: capabilities.paper_search(
                actor=self._actor,
                request=request,
            )
        )

    def get_download_url(
        self,
        *,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> DocumentFileUrlResponse:
        return self._executor.query(
            lambda capabilities: capabilities.paper_download(
                actor=self._actor,
                document_id=document_id,
                project_id=project_id,
            )
        )

    async def ingest_url(
        self,
        *,
        url: str,
        project_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> UploadAcceptedResponse:
        return await create_paper_ingestion_workflow(self._executor).from_url(
            actor=self._actor,
            url=url,
            project_id=project_id,
            idempotency_key=idempotency_key,
            ip_address="mcp",
        )

    def resolve_citation(
        self,
        *,
        document_id: UUID,
        style: str = "APA",
        project_id: UUID | None = None,
    ) -> CitationResult:
        return self._executor.query(
            lambda capabilities: capabilities.citations(
                actor=self._actor,
                document_id=document_id,
                style=style,
                project_id=project_id,
            )
        )
