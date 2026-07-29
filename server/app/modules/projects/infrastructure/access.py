from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.database.models import Project, ProjectCollaborator
from app.modules.projects.domain import (
    ProjectAccessFacts,
    ProjectPermission,
    ProjectPermissions,
    require_permission,
)
from app.shared.domain import AppError, FailureKind
from sqlalchemy import select
from sqlalchemy.orm import Session

ProjectPermissionName = Literal[
    "edit_project",
    "manage_papers",
    "manage_collaborators",
    "owner",
]


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

    @property
    def facts(self) -> ProjectAccessFacts:
        return ProjectAccessFacts(
            user_id=self.user_id,
            owner_id=self.project.owner_id,
            permissions=self.permissions,
        )


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
            kind=FailureKind.NOT_FOUND,
        )
    return access


def require_project_permission(
    db: Session,
    *,
    project_id: uuid.UUID,
    user_id: int,
    permission: ProjectPermissionName,
) -> ProjectAccess:
    access = require_project_access(db, project_id=project_id, user_id=user_id)
    require_permission(access.facts, ProjectPermission(permission))
    return access


def collaborator_permissions(
    collaborator: ProjectCollaborator,
) -> ProjectPermissions:
    return ProjectPermissions(
        edit_project=collaborator.can_edit_project,
        manage_papers=collaborator.can_manage_papers,
        manage_collaborators=collaborator.can_manage_collaborators,
    )
