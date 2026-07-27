"""Authorization rules shared by heterogeneous research-output models."""

from __future__ import annotations

import uuid

from app.errors import AppError
from app.policies.projects import ProjectAccess, get_project_access
from sqlalchemy.orm import Session


def require_project_research_access(
    db: Session,
    *,
    project_id: uuid.UUID,
    user_id: int,
) -> ProjectAccess:
    access = get_project_access(db, project_id=project_id, user_id=user_id)
    if access is None:
        raise AppError(
            code="project_not_found",
            message="Project not found",
            status_code=404,
        )
    return access


def can_view_research_item(
    *,
    access: ProjectAccess,
    created_by_id: int | None,
    is_shared: bool,
) -> bool:
    return is_shared or created_by_id == access.user_id


def can_manage_research_item(
    *,
    access: ProjectAccess,
    created_by_id: int | None,
) -> bool:
    """Creators manage their output; the Project owner can moderate it."""
    return access.is_owner or created_by_id == access.user_id


def require_research_item_manager(
    *,
    access: ProjectAccess,
    created_by_id: int | None,
) -> None:
    if not can_manage_research_item(
        access=access,
        created_by_id=created_by_id,
    ):
        raise AppError(
            code="research_item_permission_denied",
            message="You do not have permission to modify this research item",
            status_code=403,
        )
