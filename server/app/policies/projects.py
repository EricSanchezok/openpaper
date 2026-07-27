from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.database.models import Project, ProjectCollaborator
from app.errors import AppError
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ProjectPermissions:
    edit_project: bool = False
    manage_papers: bool = False
    manage_collaborators: bool = False

    def contains(self, requested: ProjectPermissions) -> bool:
        return (
            (not requested.edit_project or self.edit_project)
            and (not requested.manage_papers or self.manage_papers)
            and (not requested.manage_collaborators or self.manage_collaborators)
        )

    @classmethod
    def all(cls) -> ProjectPermissions:
        return cls(
            edit_project=True,
            manage_papers=True,
            manage_collaborators=True,
        )


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    project: Project
    user_id: int
    is_owner: bool
    collaborator: ProjectCollaborator | None
    permissions: ProjectPermissions

    @property
    def can_edit_project(self) -> bool:
        return self.is_owner or self.permissions.edit_project

    @property
    def can_manage_papers(self) -> bool:
        return self.is_owner or self.permissions.manage_papers

    @property
    def can_manage_collaborators(self) -> bool:
        return self.is_owner or self.permissions.manage_collaborators


def get_project_access(
    db: Session, *, project_id: uuid.UUID, user_id: int
) -> ProjectAccess | None:
    project = db.get(Project, project_id)
    if project is None:
        return None
    if project.owner_id == user_id:
        return ProjectAccess(
            project=project,
            user_id=user_id,
            is_owner=True,
            collaborator=None,
            permissions=ProjectPermissions.all(),
        )

    collaborator = db.scalar(
        select(ProjectCollaborator).where(
            ProjectCollaborator.project_id == project_id,
            ProjectCollaborator.user_id == user_id,
        )
    )
    if collaborator is None:
        return None
    return ProjectAccess(
        project=project,
        user_id=user_id,
        is_owner=False,
        collaborator=collaborator,
        permissions=ProjectPermissions(
            edit_project=collaborator.can_edit_project,
            manage_papers=collaborator.can_manage_papers,
            manage_collaborators=collaborator.can_manage_collaborators,
        ),
    )


def require_project_access(
    db: Session, *, project_id: uuid.UUID, user_id: int
) -> ProjectAccess:
    access = get_project_access(db, project_id=project_id, user_id=user_id)
    if access is None:
        raise AppError(
            code="project_not_found",
            message="Project not found",
            status_code=404,
        )
    return access


def require_project_permission(
    db: Session,
    *,
    project_id: uuid.UUID,
    user_id: int,
    permission: str,
) -> ProjectAccess:
    access = require_project_access(db, project_id=project_id, user_id=user_id)
    allowed = {
        "edit_project": access.can_edit_project,
        "manage_papers": access.can_manage_papers,
        "manage_collaborators": access.can_manage_collaborators,
        "owner": access.is_owner,
    }.get(permission)
    if allowed is None:
        raise ValueError(f"Unknown project permission: {permission}")
    if not allowed:
        raise AppError(
            code="project_permission_denied",
            message="You do not have permission to perform this project action",
            status_code=403,
        )
    return access


def collaborator_permissions(
    collaborator: ProjectCollaborator,
) -> ProjectPermissions:
    return ProjectPermissions(
        edit_project=collaborator.can_edit_project,
        manage_papers=collaborator.can_manage_papers,
        manage_collaborators=collaborator.can_manage_collaborators,
    )
