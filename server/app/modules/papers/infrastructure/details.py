"""SQLAlchemy adapter for canonical paper metadata."""

from uuid import UUID

from app.modules.papers.application.contracts.documents import DocumentResponse
from app.modules.papers.infrastructure.library_gateway import document_response
from app.modules.papers.infrastructure.repository import document_repository
from app.shared.application import Actor
from sqlalchemy.orm import Session


class SqlAlchemyPaperDetails:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> DocumentResponse | None:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        return document_response(document) if document is not None else None
