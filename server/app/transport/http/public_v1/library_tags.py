"""Typed Library tag API bound to personal LibraryPaper references."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagAssignmentResponse,
    LibraryTagCreateRequest,
    LibraryTagListResponse,
    LibraryTagResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Response, status

library_tags_router = APIRouter()


@library_tags_router.get("/tags", response_model=LibraryTagListResponse)
def list_library_tags(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagListResponse:
    return executor.query(
        lambda capabilities: capabilities.library_tags.list(actor=current_user)
    )


@library_tags_router.post(
    "/tags",
    response_model=LibraryTagResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_library_tag(
    request: LibraryTagCreateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagResponse:
    return executor.command(
        lambda capabilities: capabilities.library_tags.create(
            actor=current_user,
            request=request,
        )
    )


@library_tags_router.post(
    "/tags/assignments",
    response_model=LibraryTagAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_library_tags(
    request: LibraryTagAssignmentRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagAssignmentResponse:
    return executor.command(
        lambda capabilities: capabilities.library_tags.assign(
            actor=current_user,
            request=request,
        )
    )


@library_tags_router.delete(
    "/papers/{document_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_library_tag_assignment(
    document_id: UUID,
    tag_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.library_tags.remove(
            actor=current_user,
            document_id=document_id,
            tag_id=tag_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
