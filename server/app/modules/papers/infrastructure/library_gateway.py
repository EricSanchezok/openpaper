"""SQLAlchemy/S3 adapters for the personal Library capability."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.documents import (
    DocumentResponse,
    LibraryPaperResponse,
    LibraryPaperUpdateRequest,
    PublicPaperOwnerResponse,
)
from app.modules.papers.application.library import PublicShare
from app.modules.papers.infrastructure.models import Document, LibraryPaper
from app.modules.papers.infrastructure.repository import document_repository
from sqlalchemy import select
from sqlalchemy.orm import Session


def document_response(document: Document) -> DocumentResponse:
    return DocumentResponse.model_validate(
        {
            "document_id": document.id,
            "original_filename": document.original_filename,
            "mime_type": document.mime_type,
            "size_bytes": document.size_bytes,
            "title": document.title,
            "authors": document.authors,
            "abstract": document.abstract,
            "institutions": document.institutions,
            "keywords": document.keywords,
            "doi": document.doi,
            "journal": document.journal,
            "publisher": document.publisher,
            "publish_date": document.publish_date,
            "summary": document.summary,
            "summary_citations": document.summary_citations,
            "starter_questions": document.starter_questions,
            "processing_status": document.processing_status,
            "parser_quality": document.parser_quality,
            "parser_warning_code": document.parser_warning_code,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }
    )


def library_paper_response(entry: LibraryPaper) -> LibraryPaperResponse:
    return LibraryPaperResponse.model_validate(
        {
            "library_entry_id": entry.id,
            "user_id": entry.user_id,
            "status": entry.status,
            "last_accessed_at": entry.last_accessed_at,
            "metadata_overrides": entry.metadata_overrides,
            "is_public": entry.is_public,
            "preview_url": (
                s3_service.generate_presigned_url(entry.document.preview_s3_key)
                if entry.document.preview_s3_key
                else None
            ),
            "tags": [
                {"id": tag.id, "name": tag.name, "color": tag.color}
                for tag in entry.tags
            ],
            "document": document_response(entry.document),
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
        }
    )


class SqlAlchemyPaperLibraryGateway:
    def __init__(
        self,
        db: Session,
        *,
        document_removed: Callable[[UUID], object],
    ) -> None:
        self._db = db
        self._document_removed = document_removed

    def list(self, *, user_id: int) -> list[LibraryPaperResponse]:
        return [
            library_paper_response(entry)
            for entry in document_repository.list_library(self._db, user_id=user_id)
        ]

    def get(self, *, user_id: int, document_id: UUID) -> LibraryPaperResponse:
        return library_paper_response(
            document_repository.require_library_paper_by_document(
                self._db,
                document_id=document_id,
                user_id=user_id,
            )
        )

    def update(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperResponse:
        return library_paper_response(
            document_repository.update_library_paper(
                self._db,
                document_id=document_id,
                user_id=user_id,
                request=request,
            )
        )

    def share(self, *, user_id: int, document_id: UUID) -> str:
        return document_repository.rotate_public_share(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )

    def unshare(self, *, user_id: int, document_id: UUID) -> None:
        document_repository.revoke_public_share(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )

    def remove(self, *, user_id: int, document_id: UUID) -> None:
        document_repository.delete_library_paper(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )
        self._document_removed(document_id)

    def public_share(self, *, share_token: str) -> PublicShare:
        shared = document_repository.require_public_share(
            self._db,
            token=share_token,
        )
        return PublicShare(
            document_id=shared.document.id,
            storage_key=shared.document.s3_object_key,
            document=document_response(shared.document),
            owner=PublicPaperOwnerResponse(
                id=shared.owner.id,
                display_name=shared.owner.display_name or shared.owner.email,
            ),
        )

    def find_entry_id(self, *, user_id: int, document_id: UUID) -> UUID | None:
        return self._db.scalar(
            select(LibraryPaper.id).where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id == document_id,
            )
        )

    def attach(self, *, user_id: int, document_id: UUID) -> UUID:
        document_repository.attach_library(
            self._db,
            document_id=document_id,
            user_id=user_id,
        )
        return document_repository.require_library_paper_by_document(
            self._db,
            document_id=document_id,
            user_id=user_id,
        ).id
