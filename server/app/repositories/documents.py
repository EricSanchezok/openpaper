"""Explicit persistence boundary for canonical documents and logical references."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    LibraryPaper,
    PaperStatus,
    ProjectPaper,
)
from app.errors import AppError
from app.schemas.documents import LibraryPaperUpdateRequest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class CanonicalDocumentResult:
    document: Document
    created: bool


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    created: bool


class DocumentRepository:
    def list_library(self, db: Session, *, user_id: int) -> list[LibraryPaper]:
        return list(
            db.scalars(
                select(LibraryPaper)
                .where(LibraryPaper.user_id == user_id)
                .order_by(LibraryPaper.updated_at.desc(), LibraryPaper.id.desc())
            ).all()
        )

    def require_library_paper(
        self,
        db: Session,
        *,
        library_paper_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> LibraryPaper:
        statement = select(LibraryPaper).where(
            LibraryPaper.id == library_paper_id,
            LibraryPaper.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        entry = db.scalar(statement)
        if entry is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                status_code=404,
            )
        return entry

    def update_library_paper(
        self,
        db: Session,
        *,
        library_paper_id: uuid.UUID,
        user_id: int,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaper:
        entry = self.require_library_paper(
            db,
            library_paper_id=library_paper_id,
            user_id=user_id,
            for_update=True,
        )
        if request.status is not None:
            entry.status = request.status.value
        if request.metadata_overrides is not None:
            entry.metadata_overrides = request.metadata_overrides.model_dump(
                mode="json",
                exclude_none=True,
            )
        entry.last_accessed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(entry)
        return entry

    def delete_library_paper(
        self,
        db: Session,
        *,
        library_paper_id: uuid.UUID,
        user_id: int,
    ) -> None:
        entry = self.require_library_paper(
            db,
            library_paper_id=library_paper_id,
            user_id=user_id,
            for_update=True,
        )
        document_id = entry.document_id
        db.delete(entry)
        db.flush()
        from app.services.document_gc import schedule_document_gc

        schedule_document_gc(db, document_id=document_id)
        db.commit()

    def get_by_sha256(
        self,
        db: Session,
        *,
        sha256: str,
        for_update: bool = False,
    ) -> Document | None:
        statement = select(Document).where(Document.sha256 == sha256)
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    def get_or_create(
        self,
        db: Session,
        *,
        sha256: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        s3_object_key: str,
        created_by_id: int,
        processing_job_id: uuid.UUID,
    ) -> CanonicalDocumentResult:
        created_id = db.scalar(
            insert(Document)
            .values(
                sha256=sha256,
                original_filename=original_filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                s3_object_key=s3_object_key,
                title=original_filename,
                created_by_id=created_by_id,
                processing_status=DocumentProcessingStatus.PROCESSING.value,
                processing_job_id=processing_job_id,
            )
            .on_conflict_do_nothing(index_elements=[Document.sha256])
            .returning(Document.id)
        )
        if created_id is not None:
            document = db.get(Document, created_id)
            if document is None:
                raise RuntimeError("created_document_not_found")
            return CanonicalDocumentResult(document=document, created=True)

        document = self.get_by_sha256(db, sha256=sha256, for_update=True)
        if document is None:
            raise RuntimeError("canonical_document_conflict_not_found")
        if document.size_bytes != size_bytes:
            raise RuntimeError("sha256_size_mismatch")
        document.gc_after = None
        return CanonicalDocumentResult(document=document, created=False)

    def attach_library(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> ReferenceResult:
        created_id = db.scalar(
            insert(LibraryPaper)
            .values(
                user_id=user_id,
                document_id=document_id,
                status=PaperStatus.reading.value,
                last_accessed_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(
                index_elements=[LibraryPaper.user_id, LibraryPaper.document_id]
            )
            .returning(LibraryPaper.id)
        )
        return ReferenceResult(created=created_id is not None)

    def attach_project(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        project_id: uuid.UUID,
        added_by_id: int,
    ) -> ReferenceResult:
        created_id = db.scalar(
            insert(ProjectPaper)
            .values(
                document_id=document_id,
                project_id=project_id,
                added_by_id=added_by_id,
            )
            .on_conflict_do_nothing(
                index_elements=[ProjectPaper.project_id, ProjectPaper.document_id]
            )
            .returning(ProjectPaper.id)
        )
        return ReferenceResult(created=created_id is not None)

    def mark_for_reprocessing(
        self,
        document: Document,
        *,
        processing_job_id: uuid.UUID,
    ) -> None:
        document.processing_status = DocumentProcessingStatus.PROCESSING.value
        document.processing_job_id = processing_job_id
        document.parser_warning_code = None


document_repository = DocumentRepository()
