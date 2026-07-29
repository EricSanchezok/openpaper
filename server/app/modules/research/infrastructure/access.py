"""Authorization policy for every research-item kind."""

from __future__ import annotations

from dataclasses import dataclass

from app.database.models import ResearchItem, ResearchScopeType
from app.database.models import (
    LibraryPaper,
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.errors import AppError
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.projects.infrastructure.access import get_project_access
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ResearchItemAccess:
    can_view: bool
    can_manage: bool
    has_scope_access: bool


def research_item_visible_to(user_id: int) -> ColumnElement[bool]:
    """Return the complete SQL visibility predicate for a research item."""
    document_library_access = exists(
        select(LibraryPaper.id).where(
            LibraryPaper.document_id == ResearchItem.document_id,
            LibraryPaper.user_id == user_id,
        )
    )
    document_project_access = exists(
        select(ProjectPaper.id)
        .join(Project, Project.id == ProjectPaper.project_id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            ProjectPaper.document_id == ResearchItem.document_id,
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )
    project_access = exists(
        select(Project.id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            Project.id == ResearchItem.project_id,
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
    )
    return or_(
        ResearchItem.created_by_id == user_id,
        and_(
            ResearchItem.is_shared.is_(True),
            or_(
                and_(
                    ResearchItem.scope_type == ResearchScopeType.DOCUMENT.value,
                    or_(document_library_access, document_project_access),
                ),
                and_(
                    ResearchItem.scope_type == ResearchScopeType.PROJECT.value,
                    project_access,
                ),
            ),
        ),
    )


class ResearchItemPolicy:
    def evaluate(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchItemAccess:
        is_creator = item.created_by_id == user_id
        scope_type = ResearchScopeType(item.scope_type)

        if scope_type == ResearchScopeType.PERSONAL:
            return ResearchItemAccess(is_creator, is_creator, is_creator)

        if scope_type == ResearchScopeType.DOCUMENT:
            has_scope_access = (
                item.document_id is not None
                and get_document_access(
                    db,
                    document_id=item.document_id,
                    user_id=user_id,
                )
                is not None
            )
        else:
            has_scope_access = (
                item.project_id is not None
                and get_project_access(
                    db,
                    project_id=item.project_id,
                    user_id=user_id,
                )
                is not None
            )

        return ResearchItemAccess(
            can_view=is_creator or (item.is_shared and has_scope_access),
            can_manage=is_creator and has_scope_access,
            has_scope_access=has_scope_access,
        )

    def require_visible(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchItemAccess:
        access = self.evaluate(db, item=item, user_id=user_id)
        if not access.can_view:
            raise AppError(
                code="research_item_not_found",
                message="Research item not found",
                status_code=404,
            )
        return access

    def require_creator_manager(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchItemAccess:
        access = self.require_visible(db, item=item, user_id=user_id)
        if item.created_by_id != user_id:
            raise AppError(
                code="research_item_permission_denied",
                message="Only the creator can modify this research item",
                status_code=403,
            )
        if not access.has_scope_access:
            raise AppError(
                code="research_item_scope_access_lost",
                message="This research item is read-only until scope access is restored",
                status_code=409,
            )
        return access


research_item_policy = ResearchItemPolicy()
