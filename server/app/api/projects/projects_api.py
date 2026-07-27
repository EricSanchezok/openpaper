from __future__ import annotations

import uuid

from app.auth.dependencies import get_required_user
from app.database.database import get_db
from app.database.models import (
    AuthUser,
    AudioOverviewJob,
    Conversation,
    DataTableExtractionJob,
    JobStatus,
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.database.telemetry import track_event
from app.helpers.subscription_limits import can_user_create_project
from app.policies.projects import ProjectAccess
from app.repositories.projects import project_repository
from app.schemas.projects import (
    ProjectCapabilitiesResponse,
    ProjectCreateRequest,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
    ProjectMembershipResponse,
    ProjectOwnerResponse,
    ProjectPermissionSet,
    ProjectResponse,
    ProjectTransferRequest,
    ProjectUpdateRequest,
)
from app.schemas.user import CurrentUser
from app.errors import AppError
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

projects_router = APIRouter()


def _permissions(access: ProjectAccess) -> ProjectPermissionSet:
    return ProjectPermissionSet(
        edit_project=access.permissions.edit_project,
        manage_papers=access.permissions.manage_papers,
        manage_collaborators=access.permissions.manage_collaborators,
    )


def _project_counts(
    db: Session, *, project_id: uuid.UUID, current_user_id: int
) -> tuple[int, int, int, int, int]:
    num_papers = db.scalar(
        select(func.count(ProjectPaper.id)).where(ProjectPaper.project_id == project_id)
    )
    num_conversations = db.scalar(
        select(func.count(Conversation.id)).where(
            Conversation.conversable_type == "project",
            Conversation.conversable_id == project_id,
            Conversation.user_id == current_user_id,
        )
    )
    num_audio = db.scalar(
        select(func.count(AudioOverviewJob.id)).where(
            AudioOverviewJob.conversable_type == "project",
            AudioOverviewJob.conversable_id == project_id,
            AudioOverviewJob.status == JobStatus.COMPLETED,
        )
    )
    num_tables = db.scalar(
        select(func.count(DataTableExtractionJob.id)).where(
            DataTableExtractionJob.project_id == project_id,
            DataTableExtractionJob.status == JobStatus.COMPLETED,
        )
    )
    num_collaborators = db.scalar(
        select(func.count(ProjectCollaborator.id)).where(
            ProjectCollaborator.project_id == project_id
        )
    )
    return (
        int(num_papers or 0),
        int(num_conversations or 0),
        int(num_audio or 0),
        int(num_tables or 0),
        int(num_collaborators or 0),
    )


def _project_response(
    db: Session, *, project: Project, current_user_id: int
) -> ProjectResponse:
    access = project_repository.get_access(
        db, project_id=project.id, user_id=current_user_id
    )
    owner = db.get(AuthUser, project.owner_id)
    if owner is None:
        raise RuntimeError(f"Project {project.id} has no owner")
    (
        num_papers,
        num_conversations,
        num_audio,
        num_tables,
        num_collaborators,
    ) = _project_counts(
        db,
        project_id=project.id,
        current_user_id=current_user_id,
    )
    return ProjectResponse(
        id=project.id,
        title=project.title,
        description=project.description,
        owner=ProjectOwnerResponse(
            id=owner.id,
            display_name=owner.display_name or owner.email,
            email=owner.email,
        ),
        membership=ProjectMembershipResponse(
            kind="owner" if access.is_owner else "collaborator",
            permissions=_permissions(access),
        ),
        capabilities=ProjectCapabilitiesResponse(
            edit_project=access.can_edit_project,
            manage_papers=access.can_manage_papers,
            manage_collaborators=access.can_manage_collaborators,
            transfer=access.is_owner,
            delete=access.is_owner,
            leave=not access.is_owner,
        ),
        num_papers=num_papers,
        num_conversations=num_conversations,
        num_audio_overviews=num_audio,
        num_data_tables=num_tables,
        num_collaborators=num_collaborators,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@projects_router.post(
    "", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED
)
def create_project(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
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
    return _project_response(db, project=project, current_user_id=current_user.id)


@projects_router.get("", response_model=list[ProjectResponse])
def get_projects(
    limit: int | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> list[ProjectResponse]:
    projects = project_repository.list_accessible(
        db, user_id=current_user.id, limit=limit
    )
    return [
        _project_response(db, project=project, current_user_id=current_user.id)
        for project in projects
    ]


@projects_router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectResponse:
    access = project_repository.get_access(
        db, project_id=project_id, user_id=current_user.id
    )
    return _project_response(
        db, project=access.project, current_user_id=current_user.id
    )


@projects_router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: uuid.UUID,
    request: ProjectUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectResponse:
    project = project_repository.update(
        db,
        project_id=project_id,
        user_id=current_user.id,
        changes=request.model_dump(exclude_unset=True),
    )
    track_event("project_updated", user_id=str(current_user.id), db=db)
    return _project_response(db, project=project, current_user_id=current_user.id)


@projects_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    project_repository.delete(db, project_id=project_id, user_id=current_user.id)
    track_event("project_deleted", user_id=str(current_user.id), db=db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.get(
    "/{project_id}/members", response_model=list[ProjectMemberResponse]
)
def get_project_members(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> list[ProjectMemberResponse]:
    project, collaborators = project_repository.list_members(
        db, project_id=project_id, user_id=current_user.id
    )
    owner = db.get(AuthUser, project.owner_id)
    if owner is None:
        raise RuntimeError(f"Project {project.id} has no owner")
    result = [
        ProjectMemberResponse(
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
        ProjectMemberResponse(
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
    "/{project_id}/members/{user_id}", response_model=ProjectMemberResponse
)
def update_project_member(
    project_id: uuid.UUID,
    user_id: int,
    request: ProjectMemberUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectMemberResponse:
    collaborator = project_repository.update_member(
        db,
        project_id=project_id,
        actor_id=current_user.id,
        target_user_id=user_id,
        requested=request,
    )
    return ProjectMemberResponse(
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
    "/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_project_member(
    project_id: uuid.UUID,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    project_repository.remove_member(
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
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    project_repository.leave(db, project_id=project_id, user_id=current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.post("/{project_id}/transfer", response_model=ProjectResponse)
def transfer_project(
    project_id: uuid.UUID,
    request: ProjectTransferRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectResponse:
    project = project_repository.transfer(
        db,
        project_id=project_id,
        owner_id=current_user.id,
        new_owner_id=request.new_owner_id,
    )
    return _project_response(db, project=project, current_user_id=current_user.id)
