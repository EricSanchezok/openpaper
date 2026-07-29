from __future__ import annotations

import uuid

from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.database import get_db
from app.database.models import (
    AuthUser,
)
from app.database.telemetry import track_event
from app.services.resource_quotas import can_user_create_project
from app.repositories.projects import project_repository
from app.modules.projects.application.contracts import (
    ProjectCreateRequest,
    ProjectCollaboratorResponse,
    ProjectCollaboratorUpdateRequest,
    ProjectPermissionSet,
    ProjectResponse,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.shared.application import Actor
from app.errors import AppError
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from .responses import project_response

projects_router = APIRouter()


@projects_router.post(
    "", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED
)
def create_project(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    can_create, _reason = can_user_create_project(db, current_user)
    if not can_create:
        raise AppError(
            code="project_quota_exceeded",
            message="Project creation limit reached",
            status_code=403,
        )
    project = project_repository.create(
        db,
        owner_id=current_user.id,
        title=request.title,
        description=request.description,
    )
    track_event("project_created", user_id=str(current_user.id), db=db)
    return project_response(db, project=project, current_user_id=current_user.id)


@projects_router.get("", response_model=list[ProjectResponse])
def get_projects(
    limit: int | None = Query(default=None, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> list[ProjectResponse]:
    projects = project_repository.list_accessible(
        db, user_id=current_user.id, limit=limit
    )
    return [
        project_response(db, project=project, current_user_id=current_user.id)
        for project in projects
    ]


@projects_router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    access = project_repository.get_access(
        db, project_id=project_id, user_id=current_user.id
    )
    return project_response(db, project=access.project, current_user_id=current_user.id)


@projects_router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: uuid.UUID,
    request: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    project = project_repository.update(
        db,
        project_id=project_id,
        user_id=current_user.id,
        changes=request.model_dump(exclude_unset=True),
    )
    track_event("project_updated", user_id=str(current_user.id), db=db)
    return project_response(db, project=project, current_user_id=current_user.id)


@projects_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    project_repository.delete(db, project_id=project_id, user_id=current_user.id)
    track_event("project_deleted", user_id=str(current_user.id), db=db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.get(
    "/{project_id}/members",
    response_model=list[ProjectCollaboratorResponse],
)
def get_project_collaborators(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> list[ProjectCollaboratorResponse]:
    project, collaborators = project_repository.list_collaborators(
        db, project_id=project_id, user_id=current_user.id
    )
    owner = db.get(AuthUser, project.owner_id)
    if owner is None:
        raise RuntimeError(f"Project {project.id} has no owner")
    result = [
        ProjectCollaboratorResponse(
            user_id=owner.id,
            display_name=owner.display_name or owner.email,
            email=owner.email,
            is_owner=True,
            permissions=ProjectPermissionSet(
                edit_project=True,
                manage_papers=True,
                manage_collaborators=True,
            ),
            joined_at=project.created_at,
        )
    ]
    result.extend(
        ProjectCollaboratorResponse(
            user_id=collaborator.user_id,
            display_name=collaborator.user.display_name or collaborator.user.email,
            email=collaborator.user.email,
            is_owner=False,
            permissions=ProjectPermissionSet(
                edit_project=collaborator.can_edit_project,
                manage_papers=collaborator.can_manage_papers,
                manage_collaborators=collaborator.can_manage_collaborators,
            ),
            joined_at=collaborator.joined_at,
        )
        for collaborator in collaborators
    )
    return result


@projects_router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectCollaboratorResponse,
)
def update_project_collaborator(
    project_id: uuid.UUID,
    user_id: int,
    request: ProjectCollaboratorUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectCollaboratorResponse:
    collaborator = project_repository.update_collaborator(
        db,
        project_id=project_id,
        actor_id=current_user.id,
        target_user_id=user_id,
        requested=request,
    )
    return ProjectCollaboratorResponse(
        user_id=collaborator.user_id,
        display_name=collaborator.user.display_name or collaborator.user.email,
        email=collaborator.user.email,
        is_owner=False,
        permissions=ProjectPermissionSet(
            edit_project=collaborator.can_edit_project,
            manage_papers=collaborator.can_manage_papers,
            manage_collaborators=collaborator.can_manage_collaborators,
        ),
        joined_at=collaborator.joined_at,
    )


@projects_router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_collaborator(
    project_id: uuid.UUID,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    project_repository.remove_collaborator(
        db,
        project_id=project_id,
        actor_id=current_user.id,
        target_user_id=user_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.post("/{project_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    project_repository.leave(db, project_id=project_id, user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.post("/{project_id}/transfer", response_model=ProjectResponse)
def transfer_project(
    project_id: uuid.UUID,
    request: ProjectTransferRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    project = project_repository.transfer(
        db,
        project_id=project_id,
        owner_id=current_user.id,
        new_owner_id=request.new_owner_id,
    )
    return project_response(db, project=project, current_user_id=current_user.id)
