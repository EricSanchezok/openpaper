"""Authorization policy for every research-item kind."""

from __future__ import annotations

from dataclasses import dataclass

from app.database.models import ResearchItem, ResearchScopeType
from app.errors import AppError
from app.policies.documents import get_document_access
from app.policies.projects import get_project_access
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ResearchItemAccess:
    can_view: bool
    can_manage: bool
    has_scope_access: bool


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
