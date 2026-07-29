"""Transport-neutral paper reading and evidence-search capabilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.shared.application import Actor


@dataclass(frozen=True)
class AccessiblePaperContent:
    document_id: UUID
    title: str | None
    abstract: str | None
    raw_content: str | None


@dataclass(frozen=True)
class MatchingLine:
    document_id: UUID
    line_number: int
    content: str


class PaperContentPort(Protocol):
    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> AccessiblePaperContent | None: ...

    def project_document_ids(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> list[UUID]: ...

    def matching_lines(
        self,
        *,
        actor: Actor,
        query: str,
        document_ids: list[UUID] | None,
    ) -> list[MatchingLine]: ...


class PaperContentCapabilities:
    """One business capability shared by HTTP, Agent, and future MCP adapters."""

    def __init__(self, content: PaperContentPort) -> None:
        self._content = content

    def read(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None = None,
    ) -> AccessiblePaperContent:
        paper = self._content.get(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        if paper is None:
            raise ValueError("Paper not found or access denied")
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

    def search_all(
        self,
        *,
        actor: Actor,
        query: str,
        project_id: UUID | None = None,
        restrict_to_document_ids: list[UUID] | None = None,
    ) -> list[MatchingLine]:
        document_ids = (
            self._content.project_document_ids(actor=actor, project_id=project_id)
            if project_id is not None
            else None
        )
        if restrict_to_document_ids is not None:
            allowed = set(restrict_to_document_ids)
            document_ids = (
                list(restrict_to_document_ids)
                if document_ids is None
                else [item for item in document_ids if item in allowed]
            )
        if document_ids == []:
            return []
        return self._content.matching_lines(
            actor=actor,
            query=query,
            document_ids=document_ids,
        )
