"""SQL adapter for document membership in a model-tool paper collection."""

from __future__ import annotations

from uuid import UUID

from app.modules.papers.application.collection_access import PaperCollectionAccessPort
from app.modules.papers.application.contracts.search import (
    LibraryPaperCollection,
    PaperCollection,
    SelectedPaperCollection,
)
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.projects.infrastructure.access import get_project_access
from app.modules.projects.infrastructure.models import ProjectPaper
from app.shared.application import Actor
from sqlalchemy import select
from sqlalchemy.orm import Session


class SqlPaperCollectionAccess(PaperCollectionAccessPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def contains(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
        document_id: UUID,
    ) -> bool:
        if (
            get_document_access(
                self._session,
                document_id=document_id,
                user_id=actor.id,
            )
            is None
        ):
            return False
        if isinstance(collection, LibraryPaperCollection):
            return True
        assert isinstance(collection, SelectedPaperCollection)
        if document_id in collection.document_ids:
            return True
        for project_id in collection.project_ids:
            if (
                get_project_access(
                    self._session,
                    project_id=project_id,
                    user_id=actor.id,
                )
                is None
            ):
                continue
            if (
                self._session.scalar(
                    select(ProjectPaper.document_id).where(
                        ProjectPaper.project_id == project_id,
                        ProjectPaper.document_id == document_id,
                    )
                )
                is not None
            ):
                return True
        return False
