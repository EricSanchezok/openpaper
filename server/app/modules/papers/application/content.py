"""Transport-neutral paper reading and evidence-search capabilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.shared.application import Actor
from app.shared.domain import AppError


@dataclass(frozen=True)
class AccessiblePaperContent:
    document_id: UUID
    original_filename: str
    title: str | None
    abstract: str | None
    raw_content: str | None
    storage_key: str
    parser_markdown_storage_key: str | None


class PaperContentPort(Protocol):
    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> AccessiblePaperContent | None: ...


class PaperContentCapabilities:
    """One business capability shared by HTTP, Agent, and future MCP adapters."""

    def __init__(
        self,
        content: PaperContentPort,
        project_documents: ListAccessibleProjectDocuments,
    ) -> None:
        self._content = content
        self._project_documents = project_documents

    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> AccessiblePaperContent:
        if project_id is not None and document_id not in self._project_documents(
            actor=actor, project_id=project_id
        ):
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                status_code=404,
            )
        paper = self._content.get(
            actor=actor,
            document_id=document_id,
        )
        if paper is None:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                status_code=404,
            )
        return paper

    def search_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        query: str,
        project_id: UUID | None = None,
    ) -> list[str]:
        content = self.read(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        ).raw_content
        if not content:
            raise ValueError("File content not found")
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regex pattern: {exc}") from exc
        return [
            f"{line_number}: {line}"
            for line_number, line in enumerate(content.splitlines(), 1)
            if pattern.search(line)
        ]
