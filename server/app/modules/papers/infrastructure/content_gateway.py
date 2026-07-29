"""SQLAlchemy adapter for the paper-content application port."""

from __future__ import annotations

from uuid import UUID

from app.modules.papers.application.content import (
    AccessiblePaperContent,
)
from app.modules.papers.infrastructure.repository import document_repository
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
    ) -> AccessiblePaperContent | None:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        if document is None:
            return None
        return AccessiblePaperContent(
            document_id=document.id,
            title=document.title,
            abstract=document.abstract,
            raw_content=document.raw_content,
            storage_key=document.s3_object_key,
        )
