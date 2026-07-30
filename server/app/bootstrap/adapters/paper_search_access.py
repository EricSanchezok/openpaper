"""Cross-module authorization for paper-search collection selectors."""

from app.modules.papers.application.contracts.search import (
    PaperCollection,
    SelectedPaperCollection,
)
from app.modules.papers.application.search import PaperSearchAccessPort
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.projects.infrastructure.access import get_project_access
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from sqlalchemy.orm import Session


class SqlPaperSearchAccess(PaperSearchAccessPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def require_collection_access(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
    ) -> None:
        if not isinstance(collection, SelectedPaperCollection):
            return
        for project_id in collection.project_ids:
            if (
                get_project_access(
                    self._session,
                    project_id=project_id,
                    user_id=actor.id,
                )
                is None
            ):
                raise AppError(
                    code="paper_search_project_not_found",
                    message="A selected project was not found",
                    kind=FailureKind.NOT_FOUND,
                )
        for document_id in collection.document_ids:
            if (
                get_document_access(
                    self._session,
                    document_id=document_id,
                    user_id=actor.id,
                )
                is None
            ):
                raise AppError(
                    code="paper_search_document_not_found",
                    message="A selected paper was not found",
                    kind=FailureKind.NOT_FOUND,
                )
