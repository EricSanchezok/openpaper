"""Authorized canonical paper metadata."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.documents import DocumentResponse
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


class PaperDetailsPort(Protocol):
    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> DocumentResponse | None: ...


class GetPaperDetails:
    def __init__(
        self,
        details: PaperDetailsPort,
        project_documents: ListAccessibleProjectDocuments,
    ) -> None:
        self._details = details
        self._project_documents = project_documents

    def __call__(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> DocumentResponse:
        if project_id is not None and document_id not in self._project_documents(
            actor=actor,
            project_id=project_id,
        ):
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        result = self._details.get(actor=actor, document_id=document_id)
        if result is None:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        return result
