"""HTTP adapter for Project invitations."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_projects
from app.database.database import get_db
from app.modules.projects.application.contracts import (
    ProjectInvitationCreateRequest,
    ProjectInvitationListResponse,
    ProjectInvitationResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

router = APIRouter()


@router.post(
    "/project-invitations/{token}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
)
def accept_invitation_token(
    token: str,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_projects(db=db).accept_invitation(actor=current_user, raw_token=token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/invitations",
    response_model=ProjectInvitationListResponse,
)
def get_project_invitations(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectInvitationListResponse:
    return build_projects(db=db).invitations(
        actor=current_user,
        project_id=project_id,
    )


@router.post(
    "/projects/{project_id}/invitations",
    response_model=ProjectInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_invitation(
    project_id: UUID,
    request: ProjectInvitationCreateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectInvitationResponse:
    return build_projects(db=db).create_invitation(
        actor=current_user,
        project_id=project_id,
        request=request,
    )


@router.post(
    "/projects/{project_id}/invitations/{invitation_id}/resend",
    response_model=ProjectInvitationResponse,
)
def resend_project_invitation(
    project_id: UUID,
    invitation_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectInvitationResponse:
    return build_projects(db=db).resend_invitation(
        actor=current_user,
        project_id=project_id,
        invitation_id=invitation_id,
    )


@router.delete(
    "/projects/{project_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_project_invitation(
    project_id: UUID,
    invitation_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_projects(db=db).revoke_invitation(
        actor=current_user,
        project_id=project_id,
        invitation_id=invitation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
