"""Typed Library tag API bound to personal LibraryPaper references."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_library_tags
from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.database import get_db
from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagAssignmentResponse,
    LibraryTagCreateRequest,
    LibraryTagListResponse,
    LibraryTagResponse,
)
from app.shared.application import Actor
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

library_tags_router = APIRouter()


@library_tags_router.get("/tags", response_model=LibraryTagListResponse)
def list_library_tags(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagListResponse:
    return build_library_tags(db=db).list(actor=current_user)


@library_tags_router.post(
    "/tags",
    response_model=LibraryTagResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_library_tag(
    request: LibraryTagCreateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagResponse:
    return build_library_tags(db=db).create(actor=current_user, request=request)


@library_tags_router.post(
    "/tags/assignments",
    response_model=LibraryTagAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def assign_library_tags(
    request: LibraryTagAssignmentRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagAssignmentResponse:
    return build_library_tags(db=db).assign(actor=current_user, request=request)


@library_tags_router.delete(
    "/papers/{document_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_library_tag_assignment(
    document_id: UUID,
    tag_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_library_tags(db=db).remove(
        actor=current_user,
        document_id=document_id,
        tag_id=tag_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
