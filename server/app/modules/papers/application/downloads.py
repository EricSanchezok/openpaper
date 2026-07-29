"""Authorized paper-download capability shared by inbound transports."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.papers.application.content import PaperContentCapabilities
from app.modules.papers.application.contracts.documents import DocumentFileUrlResponse
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


class PaperDownloadSigner(Protocol):
    def sign(self, *, storage_key: str) -> str: ...


class GetPaperDownload:
    def __init__(
        self,
        content: PaperContentCapabilities,
        signer: PaperDownloadSigner,
        *,
        expires_in_seconds: int,
    ) -> None:
        self._content = content
        self._signer = signer
        self._expires_in_seconds = expires_in_seconds

    def __call__(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> DocumentFileUrlResponse:
        paper = self._content.read(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        try:
            file_url = self._signer.sign(storage_key=paper.storage_key)
        except RuntimeError as exc:
            raise AppError(
                code="document_file_url_unavailable",
                message="The document file is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        return DocumentFileUrlResponse(
            file_url=file_url,
            expires_in_seconds=self._expires_in_seconds,
        )
