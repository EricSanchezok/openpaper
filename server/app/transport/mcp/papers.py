"""Protocol-neutral MCP adapter over the existing paper application handlers.

The formal MCP server is intentionally deferred. This adapter fixes the
boundary now: a future server only validates MCP arguments and delegates here;
it never calls Scholens HTTP endpoints or repositories.
"""

from __future__ import annotations

from uuid import UUID

from app.modules.papers.application.content import PaperContentCapabilities
from app.modules.papers.application.contracts.search import (
    PaperSearchRequest,
    PaperSearchResponse,
)
from app.modules.papers.application.search import SearchPapers
from app.modules.papers.application.downloads import GetPaperDownload
from app.modules.papers.application.contracts.documents import DocumentFileUrlResponse
from app.modules.papers.application.ingestion import IngestPaper, PdfUrlSource
from app.modules.papers.application.contracts.uploads import UploadAcceptedResponse
from app.shared.application import Actor


class McpPaperTools:
    def __init__(
        self,
        *,
        actor: Actor,
        content: PaperContentCapabilities,
        search: SearchPapers,
        download: GetPaperDownload,
        ingestion: IngestPaper,
        url_source: PdfUrlSource,
    ) -> None:
        self._actor = actor
        self._content = content
        self._search = search
        self._download = download
        self._ingestion = ingestion
        self._url_source = url_source

    def read_document(
        self,
        *,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> dict[str, object]:
        paper = self._content.read(
            actor=self._actor,
            document_id=document_id,
            project_id=project_id,
        )
        return {
            "document_id": str(paper.document_id),
            "title": paper.title,
            "abstract": paper.abstract,
            "content": paper.raw_content,
        }

    def search_papers(self, request: PaperSearchRequest) -> PaperSearchResponse:
        return self._search(actor=self._actor, request=request)

    def get_download_url(
        self,
        *,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> DocumentFileUrlResponse:
        return self._download(
            actor=self._actor,
            document_id=document_id,
            project_id=project_id,
        )

    async def ingest_url(
        self,
        *,
        url: str,
        project_id: UUID | None = None,
        idempotency_key: str | None = None,
    ) -> UploadAcceptedResponse:
        return await self._ingestion.from_url(
            actor=self._actor,
            url=url,
            source=self._url_source,
            project_id=project_id,
            idempotency_key=idempotency_key,
            ip_address="mcp",
        )
