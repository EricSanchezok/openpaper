"""Explicit persistence boundary for canonical documents and logical references."""

from __future__ import annotations

import uuid
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from app.helpers.postgres import sanitize_for_postgres
from app.database.models import (
    AuthUser,
    Document,
    DocumentProcessingStatus,
    DurableJob,
    LibraryPaper,
    PaperStatus,
    ProjectPaper,
    UploadReservation,
)
from app.shared.domain import AppError
from app.helpers.paper_search import normalize_doi
from app.modules.papers.infrastructure.access import (
    get_document_access,
    require_document_access,
)
from app.modules.papers.application.contracts.documents import (
    DocumentUpdate,
    LibraryPaperUpdateRequest,
)
from app.shared.application import Actor
from sqlalchemy import select, update
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload


@dataclass(frozen=True, slots=True)
class CanonicalDocumentResult:
    document: Document
    created: bool


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    created: bool


@dataclass(frozen=True, slots=True)
class PublicLibraryPaper:
    entry: LibraryPaper
    document: Document
    owner: AuthUser


class DocumentRepository:
    def find_accessible(
        self,
        db: Session,
        *,
        document_id: object,
        user: Actor,
        update_last_accessed: bool = False,
    ) -> Document | None:
        """Return a Document only through an explicit user access check."""
        try:
            parsed_id = uuid.UUID(str(document_id))
        except (TypeError, ValueError):
            return None
        access = get_document_access(
            db,
            document_id=parsed_id,
            user_id=user.id,
        )
        if access is None:
            return None
        if update_last_accessed and access.library_paper is not None:
            access.library_paper.last_accessed_at = datetime.now(timezone.utc)
            db.flush()
        return access.document

    def update_canonical(
        self,
        db: Session,
        *,
        document: Document,
        update: DocumentUpdate,
        user: Actor | None = None,
        refresh_result: bool = True,
    ) -> Document:
        """Update canonical metadata after optional explicit access validation."""
        if user is not None:
            require_document_access(
                db,
                document_id=document.id,
                user_id=user.id,
            )
        values = update.model_dump(exclude_unset=True)
        sanitized = sanitize_for_postgres(values)
        for field, value in sanitized.items():
            setattr(document, field, value)
        if refresh_result:
            db.flush()
            db.refresh(document)
        else:
            db.flush()
        return document

    def find_by_upload_job(
        self,
        db: Session,
        *,
        upload_job_id: str,
        user: Actor,
    ) -> Document | None:
        """Return the Document produced by one of the user's durable jobs."""
        return db.scalar(
            select(Document)
            .join(DurableJob, DurableJob.document_id == Document.id)
            .join(UploadReservation, UploadReservation.id == DurableJob.id)
            .where(
                UploadReservation.id == upload_job_id,
                DurableJob.requested_by_id == user.id,
            )
        )

    def list_available_library_documents(
        self,
        db: Session,
        *,
        user: Actor,
        query: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[Document]:
        statement = (
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.user_id == user.id,
                Document.ts_vector.isnot(None),
            )
        )
        if document_ids:
            statement = statement.where(Document.id.in_(document_ids))
        if query:
            ts_query = func.to_tsquery("english", " & ".join(query.split()))
            statement = statement.where(Document.ts_vector.op("@@")(ts_query))
        return list(db.scalars(statement.order_by(Document.updated_at.desc())).all())

    def find_library_document_by_doi(
        self,
        db: Session,
        *,
        user_id: int,
        doi: str,
    ) -> Document | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        escaped = (
            normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        return db.scalars(
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.user_id == user_id,
                func.lower(Document.doi).like(f"%{escaped}", escape="\\"),
            )
        ).first()

    def list_library(self, db: Session, *, user_id: int) -> list[LibraryPaper]:
        return list(
            db.scalars(
                select(LibraryPaper)
                .options(
                    selectinload(LibraryPaper.document),
                    selectinload(LibraryPaper.tags),
                )
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

    def require_library_paper_by_document(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> LibraryPaper:
        statement = (
            select(LibraryPaper)
            .options(
                selectinload(LibraryPaper.document),
                selectinload(LibraryPaper.tags),
            )
            .where(
                LibraryPaper.document_id == document_id,
                LibraryPaper.user_id == user_id,
            )
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
        document_id: uuid.UUID,
        user_id: int,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaper:
        entry = self.require_library_paper_by_document(
            db,
            document_id=document_id,
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
        db.flush()
        db.refresh(entry)
        return entry

    def delete_library_paper(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> None:
        entry = self.require_library_paper_by_document(
            db,
            document_id=document_id,
            user_id=user_id,
            for_update=True,
        )
        document_id = entry.document_id
        db.delete(entry)
        db.flush()
        from app.modules.papers.infrastructure.garbage_collection import (
            schedule_document_gc,
        )

        schedule_document_gc(db, document_id=document_id)
        db.flush()

    def rotate_public_share(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> str:
        entry = self.require_library_paper_by_document(
            db,
            document_id=document_id,
            user_id=user_id,
            for_update=True,
        )
        token = secrets.token_urlsafe(32)
        entry.share_token_hash = hashlib.sha256(token.encode()).hexdigest()
        entry.is_public = True
        db.flush()
        return token

    def revoke_public_share(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> None:
        entry = self.require_library_paper_by_document(
            db,
            document_id=document_id,
            user_id=user_id,
            for_update=True,
        )
        entry.share_token_hash = None
        entry.is_public = False
        db.flush()

    def require_public_share(
        self,
        db: Session,
        *,
        token: str,
    ) -> PublicLibraryPaper:
        if not token or len(token) > 512:
            raise AppError(
                code="public_paper_not_found",
                message="Public paper not found",
                status_code=404,
            )
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        entry = db.scalar(
            select(LibraryPaper)
            .options(
                selectinload(LibraryPaper.document),
                selectinload(LibraryPaper.user),
            )
            .where(
                LibraryPaper.share_token_hash == token_hash,
                LibraryPaper.is_public.is_(True),
            )
        )
        if entry is None:
            raise AppError(
                code="public_paper_not_found",
                message="Public paper not found",
                status_code=404,
            )
        return PublicLibraryPaper(
            entry=entry,
            document=entry.document,
            owner=entry.user,
        )

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
        db.execute(
            update(Document)
            .where(Document.id == document_id, Document.gc_after.isnot(None))
            .values(gc_after=None)
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
        db.execute(
            update(Document)
            .where(Document.id == document_id, Document.gc_after.isnot(None))
            .values(gc_after=None)
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
