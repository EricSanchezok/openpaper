import logging

from app.database.crud.base_crud import CRUDBase
from app.database.crud.projects.project_crud import project_crud
from app.database.crud.user_repository import user_repository
from app.database.models import (
    Project,
    ProjectRole,
    ProjectRoleInvitation,
    ProjectRoles,
)
from app.helpers.email import send_general_invite_email, send_project_invite_email
from app.schemas.user import CurrentUser
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

logger = logging.getLogger(__name__)


# Pydantic models
class ProjectRoleInvitationBase(BaseModel):
    email: EmailStr
    role: ProjectRoles


class ProjectRoleInvitationCreate(ProjectRoleInvitationBase):
    project_id: str
    invited_by: int


class ProjectRoleInvitationUpdate(BaseModel):
    role: ProjectRoles | None = None


class ProjectRoleInvitationCRUD(
    CRUDBase[
        ProjectRoleInvitation,
        ProjectRoleInvitationCreate,
        ProjectRoleInvitationUpdate,
    ]
):
    def create(
        self,
        db: Session,
        *,
        obj_in: ProjectRoleInvitationCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> ProjectRoleInvitation | None:
        if user is None:
            raise ValueError(
                "user parameter is required for ProjectRoleInvitationCRUD.create"
            )
        if not project_crud.has_role(
            db,
            project_id=obj_in.project_id,
            user_id=user.id,
            role=ProjectRoles.ADMIN,
        ):
            logger.error(
                f"User {user.id} does not have admin role in project {obj_in.project_id}"
            )
            return None
        try:
            db_obj = ProjectRoleInvitation(
                project_id=obj_in.project_id,
                email=obj_in.email,
                role=obj_in.role,
                invited_by=obj_in.invited_by,
            )
            db.add(db_obj)
            if auto_commit:
                db.commit()
                db.refresh(db_obj)
            else:
                db.flush()
            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error creating {ProjectRoleInvitation.__name__}: {str(e)}",
                exc_info=True,
            )
            return None

    def get_by_project_and_email(
        self, db: Session, *, project_id: str, email: str
    ) -> ProjectRoleInvitation | None:
        return db.scalars(
            select(ProjectRoleInvitation).where(
                ProjectRoleInvitation.project_id == project_id,
                ProjectRoleInvitation.email == email,
            )
        ).first()

    def get_by_project(
        self, db: Session, *, project_id: str, user: CurrentUser
    ) -> list[ProjectRoleInvitation]:
        project = project_crud.get(db, id=project_id, user=user)

        if not project:
            return []

        return list(
            db.scalars(
                select(ProjectRoleInvitation)
                .options(
                    joinedload(ProjectRoleInvitation.inviter),
                    joinedload(ProjectRoleInvitation.project),
                )
                .where(ProjectRoleInvitation.project_id == project_id)
            )
            .unique()
            .all()
        )

    def invite_user(
        self,
        db: Session,
        *,
        project_id: str,
        email: str,
        role: ProjectRoles,
        inviting_user: CurrentUser,
    ) -> ProjectRoleInvitation | None:
        """Invite a user to a project with a specific role by creating an invitation."""
        try:
            # Check if the user is already a member of the project
            invited_user = user_repository.get_by_email(db, email=email)
            if invited_user:
                existing_role = db.scalars(
                    select(ProjectRole).where(
                        ProjectRole.project_id == project_id,
                        ProjectRole.user_id == invited_user.id,
                    )
                ).first()
                if existing_role:
                    logger.info(
                        f"User with email {email} is already a member of project {project_id}."
                    )
                    return None

            # Check if an invitation already exists
            existing_invitation = self.get_by_project_and_email(
                db, project_id=project_id, email=email
            )
            if existing_invitation:
                logger.info(
                    f"An invitation for {email} to project {project_id} already exists."
                )
                return existing_invitation

            # Create the invitation
            invitation_create = ProjectRoleInvitationCreate(
                project_id=project_id,
                email=email,
                role=role,
                invited_by=inviting_user.id,
            )
            invitation = self.create(db, obj_in=invitation_create, user=inviting_user)

            if invitation:
                project = db.get(Project, project_id)
                if not project:
                    logger.error(f"Project with id {project_id} not found.")
                    return invitation

                if invited_user:
                    send_project_invite_email(
                        to_email=email,
                        project_title=project.title or "Untitled project",
                        from_name=str(
                            inviting_user.display_name or inviting_user.email
                        ),
                    )
                else:
                    send_general_invite_email(
                        to_email=email,
                        from_name=str(
                            inviting_user.display_name or inviting_user.email
                        ),
                    )

            return invitation

        except Exception as e:
            db.rollback()
            logger.error(
                f"Error inviting user {email} to project {project_id}: {str(e)}",
                exc_info=True,
            )
            return None

    def invite_users(
        self,
        db: Session,
        *,
        project_id: str,
        invites: list[ProjectRoleInvitationBase],
        inviting_user: CurrentUser,
    ) -> list[ProjectRoleInvitation]:
        """Invite multiple users to a project with a specific role by creating invitations."""
        invitations = []
        for invite in invites:
            invitation = self.invite_user(
                db,
                project_id=project_id,
                email=invite.email,
                role=invite.role,
                inviting_user=inviting_user,
            )
            if invitation:
                invitations.append(invitation)
        return invitations

    def accept_invitation(
        self, db: Session, *, invitation_id: str, user: CurrentUser
    ) -> ProjectRole | None:
        """Accept a project invitation."""
        try:
            invitation = db.get(ProjectRoleInvitation, invitation_id)

            if not invitation or invitation.email != user.email:
                logger.warning(
                    f"Invalid invitation {invitation_id} for user {user.id} ({user.email})"
                )
                return None

            # Create a project role for the user
            project_role = ProjectRole(
                project_id=invitation.project_id,
                user_id=user.id,
                role=invitation.role,
            )
            db.add(project_role)

            # Delete the invitation
            db.delete(invitation)
            db.commit()

            return project_role

        except Exception as e:
            db.rollback()
            logger.error(
                f"Error accepting invitation {invitation_id} for user {user.id}: {str(e)}",
                exc_info=True,
            )
            return None

    def reject_invitation(
        self, db: Session, *, invitation_id: str, user: CurrentUser
    ) -> bool:
        """Reject a project invitation."""
        try:
            invitation = db.get(ProjectRoleInvitation, invitation_id)

            if not invitation or invitation.email != user.email:
                logger.warning(
                    f"Invalid invitation {invitation_id} for user {user.id} ({user.email})"
                )
                return False

            # Delete the invitation
            db.delete(invitation)
            db.commit()

            return True

        except Exception as e:
            db.rollback()
            logger.error(
                f"Error rejecting invitation {invitation_id} for user {user.id}: {str(e)}",
                exc_info=True,
            )
            return False

    def get_pending_invitations_for_email(
        self, db: Session, *, email: str
    ) -> list[ProjectRoleInvitation]:
        """Get all pending invitations for a given email."""
        return list(
            db.scalars(
                select(ProjectRoleInvitation)
                .options(
                    joinedload(ProjectRoleInvitation.inviter),
                    joinedload(ProjectRoleInvitation.project),
                )
                .where(
                    ProjectRoleInvitation.email == email,
                    ProjectRoleInvitation.accepted_at.is_(None),
                )
            )
            .unique()
            .all()
        )

    def retract_invitation(
        self, db: Session, *, invitation_id: str, user: CurrentUser
    ) -> bool:
        """Retract a project invitation."""
        try:
            invitation = db.get(ProjectRoleInvitation, invitation_id)

            if not invitation:
                logger.warning(
                    f"Invitation {invitation_id} not found for retraction by user {user.id}"
                )
                return False

            # Check if the user has admin role in the project
            if not project_crud.has_role(
                db,
                project_id=str(invitation.project_id),
                user_id=user.id,
                role=ProjectRoles.ADMIN,
            ):
                logger.warning(
                    f"User {user.id} does not have admin role in project {invitation.project_id} for retraction"
                )
                return False

            # Delete the invitation
            db.delete(invitation)
            db.commit()

            return True

        except Exception as e:
            db.rollback()
            logger.error(
                f"Error retracting invitation {invitation_id} by user {user.id}: {str(e)}",
                exc_info=True,
            )
            return False


project_role_invitation_crud = ProjectRoleInvitationCRUD(ProjectRoleInvitation)
