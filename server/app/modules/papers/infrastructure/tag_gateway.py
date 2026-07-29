"""SQLAlchemy adapter for Library tag application use cases."""

from __future__ import annotations

from uuid import UUID

from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagCreateRequest,
    LibraryTagResponse,
)
from app.modules.papers.infrastructure.tag_repository import library_tag_repository
from sqlalchemy.orm import Session


class SqlAlchemyLibraryTagGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _response(tag: object) -> LibraryTagResponse:
        from app.modules.papers.infrastructure.models import PaperTag

        if not isinstance(tag, PaperTag):
            raise TypeError("expected PaperTag")
        return LibraryTagResponse(id=tag.id, name=tag.name, color=tag.color)

    def list(self, *, user_id: int) -> list[LibraryTagResponse]:
        return [
            self._response(tag)
            for tag in library_tag_repository.list_owned(self._db, user_id=user_id)
        ]

    def create(
        self,
        *,
        user_id: int,
        request: LibraryTagCreateRequest,
    ) -> LibraryTagResponse:
        return self._response(
            library_tag_repository.create(
                self._db,
                user_id=user_id,
                name=request.name,
                color=request.color,
            )
        )

    def assign(
        self,
        *,
        user_id: int,
        request: LibraryTagAssignmentRequest,
    ) -> int:
        return library_tag_repository.assign_many(
            self._db,
            user_id=user_id,
            document_ids=request.document_ids,
            tag_ids=request.tag_ids,
        )

    def remove(
        self,
        *,
        user_id: int,
        document_id: UUID,
        tag_id: UUID,
    ) -> None:
        library_tag_repository.remove_from_document(
            self._db,
            user_id=user_id,
            document_id=document_id,
            tag_id=tag_id,
        )
