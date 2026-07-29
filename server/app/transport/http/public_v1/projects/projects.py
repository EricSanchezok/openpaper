"""HTTP adapter for Project lifecycle and collaboration."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_projects
from app.database.database import get_db
from app.modules.projects.application.contracts import (
    ProjectCollaboratorListResponse,
    ProjectCollaboratorResponse,
    ProjectCollaboratorUpdateRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

projects_router = APIRouter()


@projects_router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    return build_projects(db=db).create(actor=current_user, request=request)


@projects_router.get("", response_model=ProjectListResponse)
def get_projects(
    limit: int | None = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectListResponse:
    return build_projects(db=db).list(actor=current_user, limit=limit)


@projects_router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    return build_projects(db=db).get(actor=current_user, project_id=project_id)


@projects_router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    return build_projects(db=db).update(
        actor=current_user,
        project_id=project_id,
        request=request,
    )


@projects_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_projects(db=db).delete(actor=current_user, project_id=project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.get(
    "/{project_id}/members",
    response_model=ProjectCollaboratorListResponse,
)
def get_project_collaborators(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectCollaboratorListResponse:
    return build_projects(db=db).members(
        actor=current_user,
        project_id=project_id,
    )


@projects_router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectCollaboratorResponse,
)
def update_project_collaborator(
    project_id: UUID,
    user_id: int,
    request: ProjectCollaboratorUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectCollaboratorResponse:
    return build_projects(db=db).update_member(
        actor=current_user,
        project_id=project_id,
        user_id=user_id,
        request=request,
    )


@projects_router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_collaborator(
    project_id: UUID,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_projects(db=db).remove_member(
        actor=current_user,
        project_id=project_id,
        user_id=user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.post("/{project_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_projects(db=db).leave(actor=current_user, project_id=project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.post("/{project_id}/transfer", response_model=ProjectResponse)
def transfer_project(
    project_id: UUID,
    request: ProjectTransferRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    return build_projects(db=db).transfer(
        actor=current_user,
        project_id=project_id,
        request=request,
    )
