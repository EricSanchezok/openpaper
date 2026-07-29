"""HTTP adapter for Project invitations."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.projects.application.contracts import (
    ProjectInvitationCreateRequest,
    ProjectInvitationListResponse,
    ProjectInvitationResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Response, status

router = APIRouter()


@router.post(
    "/project-invitations/{token}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
)
def accept_invitation_token(
    token: str,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.projects.accept_invitation(
            actor=current_user,
            raw_token=token,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/invitations",
    response_model=ProjectInvitationListResponse,
)
def get_project_invitations(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectInvitationListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.invitations(
            actor=current_user,
            project_id=project_id,
        )
    )


@router.post(
    "/projects/{project_id}/invitations",
    response_model=ProjectInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_invitation(
    project_id: UUID,
    request: ProjectInvitationCreateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectInvitationResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.create_invitation(
            actor=current_user,
            project_id=project_id,
            request=request,
        )
    )


@router.post(
    "/projects/{project_id}/invitations/{invitation_id}/resend",
    response_model=ProjectInvitationResponse,
)
def resend_project_invitation(
    project_id: UUID,
    invitation_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectInvitationResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.resend_invitation(
            actor=current_user,
            project_id=project_id,
            invitation_id=invitation_id,
        )
    )


@router.delete(
    "/projects/{project_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_project_invitation(
    project_id: UUID,
    invitation_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.projects.revoke_invitation(
            actor=current_user,
            project_id=project_id,
            invitation_id=invitation_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
