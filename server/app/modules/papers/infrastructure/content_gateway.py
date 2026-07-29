"""SQLAlchemy adapter for the paper-content application port."""

from __future__ import annotations

from uuid import UUID

from app.modules.papers.application.content import (
    AccessiblePaperContent,
    MatchingLine,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.infrastructure.search_repository import (
    document_search_repository,
)
from app.modules.projects.infrastructure.document_repository import (
    project_document_repository,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


class SqlAlchemyPaperContentGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> AccessiblePaperContent | None:
        document = (
            project_document_repository.get_paper_by_project(
                self._db,
                document_id=document_id,
                project_id=project_id,
                user=actor,
            )
            if project_id is not None
            else document_repository.find_accessible(
                self._db,
                document_id=document_id,
                user=actor,
            )
        )
        if document is None:
            return None
        return AccessiblePaperContent(
            document_id=document.id,
            title=document.title,
            abstract=document.abstract,
            raw_content=document.raw_content,
        )

    def project_document_ids(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> list[UUID]:
        return project_document_repository.get_project_document_ids_by_project_id(
            self._db,
            project_id=project_id,
            user=actor,
        )

    def matching_lines(
        self,
        *,
        actor: Actor,
        query: str,
        document_ids: list[UUID] | None,
    ) -> list[MatchingLine]:
        return [
            MatchingLine(
                document_id=UUID(document_id),
                line_number=line_number,
                content=content,
            )
            for document_id, line_number, content in (
                document_search_repository.matching_lines(
                    self._db,
                    user_id=actor.id,
                    query=query,
                    document_ids=document_ids,
                )
            )
        ]
