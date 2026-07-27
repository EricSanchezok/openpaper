from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.database.models import (
    Document,
    LibraryPaper,
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.errors import AppError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class DocumentAccess:
    document: Document
    library_paper: LibraryPaper | None
    project_id: uuid.UUID | None

    @property
    def is_in_library(self) -> bool:
        return self.library_paper is not None

    @property
    def is_project_only(self) -> bool:
        return self.library_paper is None and self.project_id is not None


def get_library_paper(
    db: Session, *, document_id: uuid.UUID, user_id: int
) -> LibraryPaper | None:
    return db.scalar(
        select(LibraryPaper).where(
            LibraryPaper.document_id == document_id,
            LibraryPaper.user_id == user_id,
        )
    )


def _accessible_project_id(
    db: Session,
    *,
    document_id: uuid.UUID,
    user_id: int,
    project_id: uuid.UUID | None,
) -> uuid.UUID | None:
    statement = (
        select(ProjectPaper.project_id)
        .join(Project, Project.id == ProjectPaper.project_id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            ProjectPaper.document_id == document_id,
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )
    if project_id is not None:
        statement = statement.where(ProjectPaper.project_id == project_id)
    return db.scalar(statement.limit(1))


def get_document_access(
    db: Session,
    *,
    document_id: uuid.UUID,
    user_id: int,
    project_id: uuid.UUID | None = None,
) -> DocumentAccess | None:
    library_paper = get_library_paper(
        db,
        document_id=document_id,
        user_id=user_id,
    )
    if library_paper is not None and project_id is None:
        document = db.get(Document, document_id)
        if document is None:
            return None
        return DocumentAccess(
            document=document,
            library_paper=library_paper,
            project_id=None,
        )

    accessible_project_id = _accessible_project_id(
        db,
        document_id=document_id,
        user_id=user_id,
        project_id=project_id,
    )
    if accessible_project_id is None:
        return None
    document = db.get(Document, document_id)
    if document is None:
        return None
    return DocumentAccess(
        document=document,
        library_paper=library_paper,
        project_id=accessible_project_id,
    )


def require_document_access(
    db: Session,
    *,
    document_id: uuid.UUID,
    user_id: int,
    project_id: uuid.UUID | None = None,
) -> DocumentAccess:
    access = get_document_access(
        db,
        document_id=document_id,
        user_id=user_id,
        project_id=project_id,
    )
    if access is None:
        raise AppError(
            code="paper_not_found",
            message="Paper not found",
            status_code=404,
        )
    return access


def require_library_paper(
    db: Session, *, document_id: uuid.UUID, user_id: int
) -> LibraryPaper:
    library_paper = get_library_paper(
        db,
        document_id=document_id,
        user_id=user_id,
    )
    if library_paper is None:
        raise AppError(
            code="library_paper_not_found",
            message="Paper is not in your library",
            status_code=404,
        )
    return library_paper
