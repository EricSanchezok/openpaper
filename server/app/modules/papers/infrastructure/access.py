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
from app.modules.papers.domain import (
    DocumentAccessDecision,
    classify_document_access,
)
from app.shared.domain import AppError, FailureKind
from sqlalchemy import ColumnElement, and_, exists, or_, select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ResolvedDocumentAccess:
    document: Document
    library_paper: LibraryPaper | None
    decision: DocumentAccessDecision


def accessible_document_condition(*, user_id: int) -> ColumnElement[bool]:
    """SQL predicate for every document the user may currently read.

    A Library collection is an access view: personal LibraryPaper membership
    plus papers reachable through an owned or collaborative Project. The
    correlated EXISTS clauses keep Document as the unique outer row.
    """

    in_personal_library = exists(
        select(LibraryPaper.id).where(
            LibraryPaper.document_id == Document.id,
            LibraryPaper.user_id == user_id,
        )
    )
    in_accessible_project = exists(
        select(ProjectPaper.document_id)
        .join(Project, Project.id == ProjectPaper.project_id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            ProjectPaper.document_id == Document.id,
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )
    return or_(in_personal_library, in_accessible_project)


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
) -> ResolvedDocumentAccess | None:
    library_paper = get_library_paper(
        db,
        document_id=document_id,
        user_id=user_id,
    )
    accessible_project_id = _accessible_project_id(
        db,
        document_id=document_id,
        user_id=user_id,
        project_id=project_id,
    )
    decision = classify_document_access(
        has_library_entry=library_paper is not None,
        accessible_project_id=accessible_project_id,
        project_was_requested=project_id is not None,
    )
    if decision is None:
        return None
    document = db.get(Document, document_id)
    if document is None:
        return None
    return ResolvedDocumentAccess(
        document=document,
        library_paper=library_paper,
        decision=decision,
    )


def require_document_access(
    db: Session,
    *,
    document_id: uuid.UUID,
    user_id: int,
    project_id: uuid.UUID | None = None,
) -> ResolvedDocumentAccess:
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
            kind=FailureKind.NOT_FOUND,
        )
    return access
