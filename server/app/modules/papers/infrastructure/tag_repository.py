"""Explicit persistence for user-owned Library tags and assignments."""

from __future__ import annotations

import uuid

from app.database.models import LibraryPaper, LibraryPaperTag, PaperTag
from app.errors import AppError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


def _normalized_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise AppError(
            code="library_tag_name_invalid",
            message="Tag name cannot be empty",
            status_code=422,
        )
    return normalized


class LibraryTagRepository:
    @staticmethod
    def list_owned(db: Session, *, user_id: int) -> list[PaperTag]:
        return list(
            db.scalars(
                select(PaperTag)
                .where(PaperTag.user_id == user_id)
                .order_by(func.lower(PaperTag.name), PaperTag.id)
            ).all()
        )

    @staticmethod
    def _find_by_name(
        db: Session,
        *,
        user_id: int,
        name: str,
    ) -> PaperTag | None:
        return db.scalar(
            select(PaperTag).where(
                PaperTag.user_id == user_id,
                func.lower(PaperTag.name) == name.lower(),
            )
        )

    def create(
        self,
        db: Session,
        *,
        user_id: int,
        name: str,
        color: str | None,
    ) -> PaperTag:
        normalized = _normalized_name(name)
        if self._find_by_name(db, user_id=user_id, name=normalized) is not None:
            raise AppError(
                code="library_tag_already_exists",
                message="A tag with this name already exists",
                status_code=409,
            )
        tag_id = uuid.uuid4()
        created_id = db.scalar(
            insert(PaperTag)
            .values(
                id=tag_id,
                name=normalized,
                color=color,
                user_id=user_id,
            )
            .on_conflict_do_nothing(index_elements=[PaperTag.user_id, PaperTag.name])
            .returning(PaperTag.id)
        )
        if created_id is None:
            raise AppError(
                code="library_tag_already_exists",
                message="A tag with this name already exists",
                status_code=409,
            )
        tag = db.get(PaperTag, created_id)
        if tag is None:
            raise RuntimeError("created_library_tag_not_found")
        db.flush()
        db.refresh(tag)
        return tag

    def get_or_create(
        self,
        db: Session,
        *,
        user_id: int,
        name: str,
        color: str | None = None,
    ) -> PaperTag:
        """Return a normalized user tag, creating it in the caller's transaction."""
        normalized = _normalized_name(name)
        existing = self._find_by_name(db, user_id=user_id, name=normalized)
        if existing is not None:
            return existing
        tag_id = uuid.uuid4()
        created_id = db.scalar(
            insert(PaperTag)
            .values(
                id=tag_id,
                name=normalized,
                color=color,
                user_id=user_id,
            )
            .on_conflict_do_nothing(index_elements=[PaperTag.user_id, PaperTag.name])
            .returning(PaperTag.id)
        )
        if created_id is None:
            existing = self._find_by_name(
                db,
                user_id=user_id,
                name=normalized,
            )
            if existing is None:
                raise RuntimeError("library_tag_conflict_not_found")
            return existing
        tag = db.get(PaperTag, created_id)
        if tag is None:
            raise RuntimeError("created_library_tag_not_found")
        return tag

    @staticmethod
    def assign_to_document(
        db: Session,
        *,
        user_id: int,
        document_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> bool:
        library_paper_id = db.scalar(
            select(LibraryPaper.id).where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id == document_id,
            )
        )
        if library_paper_id is None:
            raise AppError(
                code="library_paper_not_found",
                message="Paper not found in your Library",
                status_code=404,
            )
        tag_exists = db.scalar(
            select(PaperTag.id).where(
                PaperTag.id == tag_id,
                PaperTag.user_id == user_id,
            )
        )
        if tag_exists is None:
            raise AppError(
                code="library_tag_not_found",
                message="Library tag not found",
                status_code=404,
            )
        created_id = db.scalar(
            insert(LibraryPaperTag)
            .values(library_paper_id=library_paper_id, tag_id=tag_id)
            .on_conflict_do_nothing(
                index_elements=[
                    LibraryPaperTag.library_paper_id,
                    LibraryPaperTag.tag_id,
                ]
            )
            .returning(LibraryPaperTag.tag_id)
        )
        db.flush()
        return created_id is not None

    @staticmethod
    def assign_many(
        db: Session,
        *,
        user_id: int,
        document_ids: list[uuid.UUID],
        tag_ids: list[uuid.UUID],
    ) -> int:
        library_entries = list(
            db.execute(
                select(LibraryPaper.document_id, LibraryPaper.id).where(
                    LibraryPaper.user_id == user_id,
                    LibraryPaper.document_id.in_(document_ids),
                )
            ).tuples()
        )
        library_by_document = dict(library_entries)
        if set(library_by_document) != set(document_ids):
            raise AppError(
                code="library_paper_not_found",
                message="One or more papers were not found in your Library",
                status_code=404,
            )
        owned_tag_ids = set(
            db.scalars(
                select(PaperTag.id).where(
                    PaperTag.user_id == user_id,
                    PaperTag.id.in_(tag_ids),
                )
            ).all()
        )
        if owned_tag_ids != set(tag_ids):
            raise AppError(
                code="library_tag_not_found",
                message="One or more Library tags were not found",
                status_code=404,
            )

        rows = [
            {
                "library_paper_id": library_by_document[document_id],
                "tag_id": tag_id,
            }
            for document_id in document_ids
            for tag_id in tag_ids
        ]
        created_ids = list(
            db.scalars(
                insert(LibraryPaperTag)
                .values(rows)
                .on_conflict_do_nothing(
                    index_elements=[
                        LibraryPaperTag.library_paper_id,
                        LibraryPaperTag.tag_id,
                    ]
                )
                .returning(LibraryPaperTag.tag_id)
            ).all()
        )
        db.flush()
        return len(created_ids)

    @staticmethod
    def remove_from_document(
        db: Session,
        *,
        user_id: int,
        document_id: uuid.UUID,
        tag_id: uuid.UUID,
    ) -> None:
        association = db.scalar(
            select(LibraryPaperTag)
            .join(
                LibraryPaper,
                LibraryPaper.id == LibraryPaperTag.library_paper_id,
            )
            .join(PaperTag, PaperTag.id == LibraryPaperTag.tag_id)
            .where(
                LibraryPaper.user_id == user_id,
                LibraryPaper.document_id == document_id,
                PaperTag.user_id == user_id,
                PaperTag.id == tag_id,
            )
        )
        if association is None:
            raise AppError(
                code="library_tag_assignment_not_found",
                message="Tag assignment not found",
                status_code=404,
            )
        db.delete(association)
        db.flush()


library_tag_repository = LibraryTagRepository()
