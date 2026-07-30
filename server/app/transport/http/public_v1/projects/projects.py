"""HTTP adapter for Project lifecycle and collaboration."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
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
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Query, Response, status

projects_router = APIRouter()


@projects_router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ProjectCreateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.create(
            actor=current_user,
            operation=operation,
            request=request,
        )
    )


@projects_router.get("", response_model=ProjectListResponse)
def get_projects(
    limit: int | None = Query(default=None, ge=1, le=100),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.list(
            actor=current_user,
            limit=limit,
        )
    )


@projects_router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.get(
            actor=current_user,
            project_id=project_id,
        )
    )


@projects_router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.update(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            request=request,
        )
    )


@projects_router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.projects.delete(
            actor=current_user,
            operation=operation,
            project_id=project_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.get(
    "/{project_id}/members",
    response_model=ProjectCollaboratorListResponse,
)
def get_project_collaborators(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectCollaboratorListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.members(
            actor=current_user,
            project_id=project_id,
        )
    )


@projects_router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectCollaboratorResponse,
)
def update_project_collaborator(
    project_id: UUID,
    user_id: int,
    request: ProjectCollaboratorUpdateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectCollaboratorResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.update_member(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            user_id=user_id,
            request=request,
        )
    )


@projects_router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_collaborator(
    project_id: UUID,
    user_id: int,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.projects.remove_member(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            user_id=user_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.post("/{project_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_project(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.projects.leave(
            actor=current_user,
            operation=operation,
            project_id=project_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@projects_router.post("/{project_id}/transfer", response_model=ProjectResponse)
def transfer_project(
    project_id: UUID,
    request: ProjectTransferRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.transfer(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            request=request,
        )
    )
