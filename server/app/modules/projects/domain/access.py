"""Pure Project authorization values and decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.shared.domain import AppError, FailureKind


class ProjectPermission(str, Enum):
    EDIT_PROJECT = "edit_project"
    MANAGE_PAPERS = "manage_papers"
    MANAGE_COLLABORATORS = "manage_collaborators"
    OWNER = "owner"


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
        return cls(True, True, True)


@dataclass(frozen=True, slots=True)
class ProjectAccessFacts:
    user_id: int
    owner_id: int
    permissions: ProjectPermissions

    @property
    def is_owner(self) -> bool:
        return self.user_id == self.owner_id

    def allows(self, permission: ProjectPermission) -> bool:
        return {
            ProjectPermission.EDIT_PROJECT: (
                self.is_owner or self.permissions.edit_project
            ),
            ProjectPermission.MANAGE_PAPERS: (
                self.is_owner or self.permissions.manage_papers
            ),
            ProjectPermission.MANAGE_COLLABORATORS: (
                self.is_owner or self.permissions.manage_collaborators
            ),
            ProjectPermission.OWNER: self.is_owner,
        }[permission]


def require_permission(
    access: ProjectAccessFacts,
    permission: ProjectPermission,
) -> None:
    if not access.allows(permission):
        raise AppError(
            code="project_permission_denied",
            message="You do not have permission to perform this project action",
            kind=FailureKind.PERMISSION_DENIED,
        )


def require_grant_subset(
    access: ProjectAccessFacts,
    requested: ProjectPermissions,
) -> None:
    if not access.is_owner and not access.permissions.contains(requested):
        raise AppError(
            code="project_permission_escalation",
            message="You cannot manage permissions you do not have",
            kind=FailureKind.PERMISSION_DENIED,
        )


def is_distinct_non_owner_member(
    *,
    actor_id: int,
    target_user_id: int,
    owner_id: int,
) -> bool:
    return actor_id != target_user_id and target_user_id != owner_id


def require_member_can_leave(*, user_id: int, owner_id: int) -> None:
    if user_id == owner_id:
        raise AppError(
            code="project_owner_must_transfer",
            message="Transfer or delete the project before leaving",
            kind=FailureKind.CONFLICT,
        )
