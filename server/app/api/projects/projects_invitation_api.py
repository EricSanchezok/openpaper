from __future__ import annotations

import uuid

from app.auth.dependencies import get_required_user
from app.database.database import get_db
from app.database.models import AuthUser, Project, ProjectInvitation
from app.helpers.email import send_project_invite_email
from app.repositories.projects import CreatedInvitation, project_repository
from app.schemas.projects import (
    ProjectInvitationCreateRequest,
    ProjectInvitationResponse,
    ProjectPermissionSet,
)
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

router = APIRouter()


def _invitation_response(
    db: Session, *, invitation_id: uuid.UUID
) -> ProjectInvitationResponse:
    invitation = db.get(ProjectInvitation, invitation_id)
    if invitation is None:
        raise RuntimeError(f"Invitation {invitation_id} disappeared after commit")
    project = db.get(Project, invitation.project_id)
    inviter = db.get(AuthUser, invitation.invited_by_id)
    if project is None or inviter is None:
        raise RuntimeError(f"Invitation {invitation_id} has invalid relationships")
    return ProjectInvitationResponse(
        id=invitation.id,
        project_id=invitation.project_id,
        project_name=project.title,
        email=invitation.email,
        invited_by=inviter.display_name or inviter.email,
        permissions=ProjectPermissionSet(
            edit_project=invitation.can_edit_project,
            manage_papers=invitation.can_manage_papers,
            manage_collaborators=invitation.can_manage_collaborators,
        ),
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


def _send_invitation(
    db: Session, *, created: CreatedInvitation, inviter: CurrentUser
) -> None:
    project = db.get(Project, created.invitation.project_id)
    if project is None:
        raise RuntimeError("Invitation project disappeared after commit")
    send_project_invite_email(
        to_email=created.invitation.email,
        from_name=str(inviter.display_name or inviter.email),
        project_title=project.title,
        invitation_token=created.raw_token,
    )


@router.get("/project-invitations", response_model=list[ProjectInvitationResponse])
def get_user_invitations(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> list[ProjectInvitationResponse]:
    invitations = project_repository.list_user_invitations(
        db, email=str(current_user.email)
    )
    return [
        _invitation_response(db, invitation_id=invitation.id)
        for invitation in invitations
    ]


@router.post(
    "/project-invitations/token/{token}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
)
def accept_invitation_token(
    token: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    project_repository.accept_invitation_token(
        db,
        raw_token=token,
        user_id=current_user.id,
        email=str(current_user.email),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/project-invitations/{invitation_id}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
)
def accept_invitation_id(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    project_repository.accept_invitation_id(
        db,
        invitation_id=invitation_id,
        user_id=current_user.id,
        email=str(current_user.email),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/project-invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def decline_invitation(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    project_repository.decline_invitation(
        db,
        invitation_id=invitation_id,
        email=str(current_user.email),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/invitations",
    response_model=list[ProjectInvitationResponse],
)
def get_project_invitations(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> list[ProjectInvitationResponse]:
    invitations = project_repository.list_project_invitations(
        db, project_id=project_id, actor_id=current_user.id
    )
    return [
        _invitation_response(db, invitation_id=invitation.id)
        for invitation in invitations
    ]


@router.post(
    "/projects/{project_id}/invitations",
    response_model=ProjectInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_invitation(
    project_id: uuid.UUID,
    request: ProjectInvitationCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectInvitationResponse:
    created = project_repository.create_invitation(
        db,
        project_id=project_id,
        actor_id=current_user.id,
        email=str(request.email),
        requested=request,
    )
    _send_invitation(db, created=created, inviter=current_user)
    return _invitation_response(db, invitation_id=created.invitation.id)


@router.post(
    "/projects/{project_id}/invitations/{invitation_id}/resend",
    response_model=ProjectInvitationResponse,
)
def resend_project_invitation(
    project_id: uuid.UUID,
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectInvitationResponse:
    created = project_repository.resend_invitation(
        db,
        project_id=project_id,
        invitation_id=invitation_id,
        actor_id=current_user.id,
    )
    _send_invitation(db, created=created, inviter=current_user)
    return _invitation_response(db, invitation_id=created.invitation.id)


@router.delete(
    "/projects/{project_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_project_invitation(
    project_id: uuid.UUID,
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    project_repository.revoke_invitation(
        db,
        project_id=project_id,
        invitation_id=invitation_id,
        actor_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
