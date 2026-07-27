from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.database.models import (
    AuthUser,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
)
from app.errors import AppError
from app.policies.projects import (
    ProjectAccess,
    ProjectPermissions,
    collaborator_permissions,
    get_project_access,
    require_project_access,
    require_project_permission,
)
from app.schemas.projects import ProjectPermissionSet
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

INVITATION_TTL = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class CreatedInvitation:
    invitation: ProjectInvitation
    raw_token: str


def _normalized_email(email: str) -> str:
    return email.strip().casefold()


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _permission_set(value: ProjectPermissionSet) -> ProjectPermissions:
    return ProjectPermissions(
        edit_project=value.edit_project,
        manage_papers=value.manage_papers,
        manage_collaborators=value.manage_collaborators,
    )


def _invitation_permissions(
    invitation: ProjectInvitation,
) -> ProjectPermissions:
    return ProjectPermissions(
        edit_project=invitation.can_edit_project,
        manage_papers=invitation.can_manage_papers,
        manage_collaborators=invitation.can_manage_collaborators,
    )


def _require_grant_subset(actor: ProjectAccess, requested: ProjectPermissions) -> None:
    if not actor.permissions.contains(requested):
        raise AppError(
            code="project_permission_escalation",
            message="You cannot manage permissions you do not have",
            status_code=403,
        )


class ProjectRepository:
    def create(
        self, db: Session, *, owner_id: int, title: str, description: str | None
    ) -> Project:
        project = Project(owner_id=owner_id, title=title, description=description)
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    def get_access(
        self, db: Session, *, project_id: uuid.UUID, user_id: int
    ) -> ProjectAccess:
        return require_project_access(db, project_id=project_id, user_id=user_id)

    def touch(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        commit: bool = True,
    ) -> None:
        project = db.get(Project, project_id)
        if project is None:
            return
        project.updated_at = datetime.now(timezone.utc)
        if commit:
            db.commit()
        else:
            db.flush()

    def list_accessible(
        self, db: Session, *, user_id: int, limit: int | None = None
    ) -> list[Project]:
        statement = (
            select(Project)
            .outerjoin(
                ProjectCollaborator,
                ProjectCollaborator.project_id == Project.id,
            )
            .where(
                or_(
                    Project.owner_id == user_id,
                    ProjectCollaborator.user_id == user_id,
                )
            )
            .options(joinedload(Project.owner))
            .order_by(Project.updated_at.desc(), Project.id)
            .distinct()
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(db.scalars(statement).unique().all())

    def update(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        user_id: int,
        changes: dict[str, object],
    ) -> Project:
        access = require_project_permission(
            db,
            project_id=project_id,
            user_id=user_id,
            permission="edit_project",
        )
        for field, value in changes.items():
            setattr(access.project, field, value)
        db.commit()
        db.refresh(access.project)
        return access.project

    def delete(self, db: Session, *, project_id: uuid.UUID, user_id: int) -> None:
        access = require_project_permission(
            db,
            project_id=project_id,
            user_id=user_id,
            permission="owner",
        )
        db.delete(access.project)
        db.commit()

    def list_members(
        self, db: Session, *, project_id: uuid.UUID, user_id: int
    ) -> tuple[Project, list[ProjectCollaborator]]:
        access = require_project_access(db, project_id=project_id, user_id=user_id)
        collaborators = list(
            db.scalars(
                select(ProjectCollaborator)
                .where(ProjectCollaborator.project_id == project_id)
                .options(joinedload(ProjectCollaborator.user))
                .order_by(ProjectCollaborator.joined_at, ProjectCollaborator.id)
            ).all()
        )
        return access.project, collaborators

    def update_member(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        target_user_id: int,
        requested: ProjectPermissionSet,
    ) -> ProjectCollaborator:
        actor = require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        if actor_id == target_user_id or actor.project.owner_id == target_user_id:
            raise AppError(
                code="project_member_not_manageable",
                message="This project member cannot be modified",
                status_code=409,
            )
        target = db.scalar(
            select(ProjectCollaborator).where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == target_user_id,
            )
        )
        if target is None:
            raise AppError(
                code="project_member_not_found",
                message="Project member not found",
                status_code=404,
            )

        requested_permissions = _permission_set(requested)
        current_permissions = collaborator_permissions(target)
        _require_grant_subset(actor, requested_permissions)
        if not actor.is_owner and not actor.permissions.contains(current_permissions):
            raise AppError(
                code="project_member_not_manageable",
                message="You cannot modify a member with permissions you do not have",
                status_code=403,
            )

        target.can_edit_project = requested.edit_project
        target.can_manage_papers = requested.manage_papers
        target.can_manage_collaborators = requested.manage_collaborators
        db.commit()
        db.refresh(target)
        return target

    def remove_member(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        target_user_id: int,
    ) -> None:
        actor = require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        if actor_id == target_user_id or actor.project.owner_id == target_user_id:
            raise AppError(
                code="project_member_not_manageable",
                message="This project member cannot be removed",
                status_code=409,
            )
        target = db.scalar(
            select(ProjectCollaborator).where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == target_user_id,
            )
        )
        if target is None:
            raise AppError(
                code="project_member_not_found",
                message="Project member not found",
                status_code=404,
            )
        if not actor.is_owner and not actor.permissions.contains(
            collaborator_permissions(target)
        ):
            raise AppError(
                code="project_member_not_manageable",
                message="You cannot remove a member with permissions you do not have",
                status_code=403,
            )
        db.delete(target)
        db.commit()

    def leave(self, db: Session, *, project_id: uuid.UUID, user_id: int) -> None:
        access = require_project_access(db, project_id=project_id, user_id=user_id)
        if access.is_owner:
            raise AppError(
                code="project_owner_must_transfer",
                message="Transfer or delete the project before leaving",
                status_code=409,
            )
        if access.collaborator is None:
            raise RuntimeError("Non-owner project access has no collaborator")
        db.delete(access.collaborator)
        db.commit()

    def transfer(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        owner_id: int,
        new_owner_id: int,
    ) -> Project:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=owner_id,
            permission="owner",
        )
        project = db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                status_code=404,
            )
        new_owner_membership = db.scalar(
            select(ProjectCollaborator).where(
                ProjectCollaborator.project_id == project_id,
                ProjectCollaborator.user_id == new_owner_id,
            )
        )
        if new_owner_membership is None:
            raise AppError(
                code="project_new_owner_not_collaborator",
                message="The new owner must already be a collaborator",
                status_code=409,
            )

        db.delete(new_owner_membership)
        db.add(
            ProjectCollaborator(
                project_id=project_id,
                user_id=owner_id,
                can_edit_project=True,
                can_manage_papers=True,
                can_manage_collaborators=True,
            )
        )
        project.owner_id = new_owner_id
        db.commit()
        db.refresh(project)
        return project

    def create_invitation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        actor_id: int,
        email: str,
        requested: ProjectPermissionSet,
    ) -> CreatedInvitation:
        actor = require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        requested_permissions = _permission_set(requested)
        if not actor.permissions.contains(requested_permissions):
            raise AppError(
                code="project_permission_escalation",
                message="You cannot grant a permission you do not have",
                status_code=403,
            )

        normalized_email = _normalized_email(email)
        existing_user = db.scalar(
            select(AuthUser).where(AuthUser.email == normalized_email)
        )
        if existing_user is not None:
            if existing_user.id == actor.project.owner_id:
                raise AppError(
                    code="project_member_exists",
                    message="This user already belongs to the project",
                    status_code=409,
                )
            existing_member = db.scalar(
                select(ProjectCollaborator).where(
                    ProjectCollaborator.project_id == project_id,
                    ProjectCollaborator.user_id == existing_user.id,
                )
            )
            if existing_member is not None:
                raise AppError(
                    code="project_member_exists",
                    message="This user already belongs to the project",
                    status_code=409,
                )

        now = datetime.now(timezone.utc)
        active = db.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.email == normalized_email,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
                ProjectInvitation.expires_at > now,
            )
        )
        if active is not None:
            _require_grant_subset(actor, _invitation_permissions(active))
            active.revoked_at = now

        raw_token = secrets.token_urlsafe(32)
        invitation = ProjectInvitation(
            project_id=project_id,
            email=normalized_email,
            token_hash=_token_hash(raw_token),
            invited_by_id=actor_id,
            can_edit_project=requested.edit_project,
            can_manage_papers=requested.manage_papers,
            can_manage_collaborators=requested.manage_collaborators,
            expires_at=now + INVITATION_TTL,
        )
        db.add(invitation)
        db.commit()
        db.refresh(invitation)
        return CreatedInvitation(invitation=invitation, raw_token=raw_token)

    def list_project_invitations(
        self, db: Session, *, project_id: uuid.UUID, actor_id: int
    ) -> list[ProjectInvitation]:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        now = datetime.now(timezone.utc)
        return list(
            db.scalars(
                select(ProjectInvitation)
                .where(
                    ProjectInvitation.project_id == project_id,
                    ProjectInvitation.accepted_at.is_(None),
                    ProjectInvitation.revoked_at.is_(None),
                    ProjectInvitation.expires_at > now,
                )
                .options(
                    joinedload(ProjectInvitation.invited_by),
                    joinedload(ProjectInvitation.project),
                )
                .order_by(ProjectInvitation.created_at.desc())
            ).all()
        )

    def list_user_invitations(
        self, db: Session, *, email: str
    ) -> list[ProjectInvitation]:
        now = datetime.now(timezone.utc)
        return list(
            db.scalars(
                select(ProjectInvitation)
                .where(
                    ProjectInvitation.email == _normalized_email(email),
                    ProjectInvitation.accepted_at.is_(None),
                    ProjectInvitation.revoked_at.is_(None),
                    ProjectInvitation.expires_at > now,
                )
                .options(
                    joinedload(ProjectInvitation.invited_by),
                    joinedload(ProjectInvitation.project),
                )
                .order_by(ProjectInvitation.created_at.desc())
            ).all()
        )

    def _accept_invitation(
        self,
        db: Session,
        *,
        invitation: ProjectInvitation | None,
        user_id: int,
        email: str,
    ) -> ProjectCollaborator:
        now = datetime.now(timezone.utc)
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.revoked_at is not None
            or invitation.expires_at <= now
            or invitation.email != _normalized_email(email)
        ):
            raise AppError(
                code="project_invitation_invalid",
                message="Invitation is invalid or expired",
                status_code=404,
            )
        project = db.get(Project, invitation.project_id)
        if project is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                status_code=404,
            )
        if project.owner_id == user_id:
            raise AppError(
                code="project_member_exists",
                message="This user already belongs to the project",
                status_code=409,
            )
        existing = db.scalar(
            select(ProjectCollaborator).where(
                ProjectCollaborator.project_id == invitation.project_id,
                ProjectCollaborator.user_id == user_id,
            )
        )
        if existing is not None:
            invitation.accepted_at = now
            db.commit()
            return existing

        inviter_access = get_project_access(
            db,
            project_id=invitation.project_id,
            user_id=invitation.invited_by_id,
        )
        requested = _invitation_permissions(invitation)
        if (
            inviter_access is None
            or not inviter_access.can_manage_collaborators
            or not inviter_access.permissions.contains(requested)
        ):
            raise AppError(
                code="project_invitation_authority_revoked",
                message="The inviter no longer has permission to grant this access",
                status_code=409,
            )

        collaborator = ProjectCollaborator(
            project_id=invitation.project_id,
            user_id=user_id,
            can_edit_project=invitation.can_edit_project,
            can_manage_papers=invitation.can_manage_papers,
            can_manage_collaborators=invitation.can_manage_collaborators,
        )
        invitation.accepted_at = now
        db.add(collaborator)
        db.commit()
        db.refresh(collaborator)
        return collaborator

    def accept_invitation_token(
        self, db: Session, *, raw_token: str, user_id: int, email: str
    ) -> ProjectCollaborator:
        invitation = db.scalar(
            select(ProjectInvitation)
            .where(ProjectInvitation.token_hash == _token_hash(raw_token))
            .with_for_update()
        )
        return self._accept_invitation(
            db,
            invitation=invitation,
            user_id=user_id,
            email=email,
        )

    def accept_invitation_id(
        self,
        db: Session,
        *,
        invitation_id: uuid.UUID,
        user_id: int,
        email: str,
    ) -> ProjectCollaborator:
        invitation = db.scalar(
            select(ProjectInvitation)
            .where(ProjectInvitation.id == invitation_id)
            .with_for_update()
        )
        return self._accept_invitation(
            db,
            invitation=invitation,
            user_id=user_id,
            email=email,
        )

    def decline_invitation(
        self,
        db: Session,
        *,
        invitation_id: uuid.UUID,
        email: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        invitation = db.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.email == _normalized_email(email),
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
                ProjectInvitation.expires_at > now,
            )
            .with_for_update()
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                status_code=404,
            )
        invitation.revoked_at = now
        db.commit()

    def revoke_invitation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        invitation_id: uuid.UUID,
        actor_id: int,
    ) -> None:
        actor = require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        invitation = db.scalar(
            select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.project_id == project_id,
            )
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                status_code=404,
            )
        _require_grant_subset(actor, _invitation_permissions(invitation))
        invitation.revoked_at = datetime.now(timezone.utc)
        db.commit()

    def resend_invitation(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        invitation_id: uuid.UUID,
        actor_id: int,
    ) -> CreatedInvitation:
        actor = require_project_permission(
            db,
            project_id=project_id,
            user_id=actor_id,
            permission="manage_collaborators",
        )
        invitation = db.scalar(
            select(ProjectInvitation)
            .where(
                ProjectInvitation.id == invitation_id,
                ProjectInvitation.project_id == project_id,
                ProjectInvitation.accepted_at.is_(None),
                ProjectInvitation.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if invitation is None:
            raise AppError(
                code="project_invitation_not_found",
                message="Project invitation not found",
                status_code=404,
            )
        _require_grant_subset(actor, _invitation_permissions(invitation))
        invitation.revoked_at = datetime.now(timezone.utc)
        db.flush()
        raw_token = secrets.token_urlsafe(32)
        replacement = ProjectInvitation(
            project_id=project_id,
            email=invitation.email,
            token_hash=_token_hash(raw_token),
            invited_by_id=actor_id,
            can_edit_project=invitation.can_edit_project,
            can_manage_papers=invitation.can_manage_papers,
            can_manage_collaborators=invitation.can_manage_collaborators,
            expires_at=datetime.now(timezone.utc) + INVITATION_TTL,
        )
        db.add(replacement)
        db.commit()
        db.refresh(replacement)
        return CreatedInvitation(invitation=replacement, raw_token=raw_token)


project_repository = ProjectRepository()
