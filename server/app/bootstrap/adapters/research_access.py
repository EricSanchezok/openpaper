"""Cross-module authorization policy for every research-item kind."""

from __future__ import annotations

from app.database.models import ResearchItem, ResearchScopeType
from app.database.models import (
    LibraryPaper,
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.modules.research.domain import (
    ResearchAccessDecision,
    ResearchAccessFacts,
    evaluate_research_access,
    require_research_manager,
    require_research_visible,
)
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.projects.infrastructure.access import get_project_access
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm import Session


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
    ) -> ResearchAccessDecision:
        is_creator = item.created_by_id == user_id
        scope_type = ResearchScopeType(item.scope_type)

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
        elif scope_type == ResearchScopeType.PROJECT:
            has_scope_access = (
                item.project_id is not None
                and get_project_access(
                    db,
                    project_id=item.project_id,
                    user_id=user_id,
                )
                is not None
            )

        else:
            has_scope_access = is_creator

        return evaluate_research_access(
            ResearchAccessFacts(
                scope_type=scope_type,
                is_creator=is_creator,
                is_shared=item.is_shared,
                has_scope_access=has_scope_access,
            )
        )

    def require_visible(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchAccessDecision:
        access = self.evaluate(db, item=item, user_id=user_id)
        require_research_visible(access)
        return access

    def require_creator_manager(
        self,
        db: Session,
        *,
        item: ResearchItem,
        user_id: int,
    ) -> ResearchAccessDecision:
        access = self.require_visible(db, item=item, user_id=user_id)
        require_research_manager(
            ResearchAccessFacts(
                scope_type=ResearchScopeType(item.scope_type),
                is_creator=item.created_by_id == user_id,
                is_shared=item.is_shared,
                has_scope_access=access.has_scope_access,
            ),
            access,
        )
        return access


research_item_policy = ResearchItemPolicy()
