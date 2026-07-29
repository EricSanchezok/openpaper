"""Typed Library tag API bound to personal LibraryPaper references."""

from __future__ import annotations

from uuid import UUID

from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.database import get_db
from app.modules.papers.infrastructure.tag_repository import library_tag_repository
from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagAssignmentResponse,
    LibraryTagCreateRequest,
    LibraryTagResponse,
)
from app.shared.application import Actor
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

library_tags_router = APIRouter()


def _tag_response(tag: object) -> LibraryTagResponse:
    from app.database.models import PaperTag

    if not isinstance(tag, PaperTag):
        raise TypeError("expected PaperTag")
    return LibraryTagResponse(id=tag.id, name=tag.name, color=tag.color)


@library_tags_router.get("/tags", response_model=list[LibraryTagResponse])
def list_library_tags(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> list[LibraryTagResponse]:
    return [
        _tag_response(tag)
        for tag in library_tag_repository.list_owned(db, user_id=current_user.id)
    ]


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
    tag = library_tag_repository.create(
        db,
        user_id=current_user.id,
        name=request.name,
        color=request.color,
    )
    return _tag_response(tag)


@library_tags_router.post(
    "/tags/assignments",
    response_model=LibraryTagAssignmentResponse,
)
def assign_library_tags(
    request: LibraryTagAssignmentRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagAssignmentResponse:
    assigned_count = library_tag_repository.assign_many(
        db,
        user_id=current_user.id,
        document_ids=request.document_ids,
        tag_ids=request.tag_ids,
    )
    return LibraryTagAssignmentResponse(assigned_count=assigned_count)


@library_tags_router.delete(
    "/papers/by-document/{document_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_library_tag_assignment(
    document_id: UUID,
    tag_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    library_tag_repository.remove_from_document(
        db,
        user_id=current_user.id,
        document_id=document_id,
        tag_id=tag_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
