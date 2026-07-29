"""HTTP adapters for typed, scope-aware Research items."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_research_items
from app.database.database import get_db
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    CreateAnnotationCommentRequest,
    CreateHighlightThreadRequest,
    DeleteHighlightThreadRequest,
    DeleteResearchItemResponse,
    ResearchItemListResponse,
    ResearchItemResponse,
    ResearchVisibilityRequest,
    UpdateAnnotationCommentRequest,
    UpdateHighlightThreadRequest,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

document_research_router = APIRouter()
project_research_router = APIRouter()
research_router = APIRouter()


@document_research_router.get(
    "/{document_id}/research-items",
    response_model=ResearchItemListResponse,
)
def list_document_research_items(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemListResponse:
    return build_research_items(db=db).list_document(
        actor=current_user,
        document_id=document_id,
    )


@project_research_router.get(
    "/{project_id}/research-items",
    response_model=ResearchItemListResponse,
)
def list_project_research_items(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemListResponse:
    return build_research_items(db=db).list_project(
        actor=current_user,
        project_id=project_id,
    )


@document_research_router.get(
    "/{document_id}/highlight-threads",
    response_model=ResearchItemListResponse,
)
def list_highlight_threads(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemListResponse:
    return build_research_items(db=db).list_document(
        actor=current_user,
        document_id=document_id,
        highlights_only=True,
    )


@document_research_router.post(
    "/{document_id}/highlight-threads",
    response_model=ResearchItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_highlight_thread(
    document_id: UUID,
    request: CreateHighlightThreadRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemResponse:
    return build_research_items(db=db).create_highlight(
        actor=current_user,
        document_id=document_id,
        request=request,
    )


@research_router.patch(
    "/highlight-threads/{thread_id}",
    response_model=ResearchItemResponse,
)
def update_highlight_thread(
    thread_id: UUID,
    request: UpdateHighlightThreadRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemResponse:
    return build_research_items(db=db).update_highlight(
        actor=current_user,
        thread_id=thread_id,
        request=request,
    )


@research_router.delete(
    "/highlight-threads/{thread_id}",
    response_model=DeleteResearchItemResponse,
)
def delete_highlight_thread(
    thread_id: UUID,
    request: DeleteHighlightThreadRequest = Depends(),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DeleteResearchItemResponse:
    return build_research_items(db=db).delete_highlight(
        actor=current_user,
        thread_id=thread_id,
        request=request,
    )


@research_router.post(
    "/highlight-threads/{thread_id}/comments",
    response_model=AnnotationCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation_comment(
    thread_id: UUID,
    request: CreateAnnotationCommentRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> AnnotationCommentResponse:
    return build_research_items(db=db).create_comment(
        actor=current_user,
        thread_id=thread_id,
        request=request,
    )


@research_router.patch(
    "/annotation-comments/{comment_id}",
    response_model=AnnotationCommentResponse,
)
def update_annotation_comment(
    comment_id: UUID,
    request: UpdateAnnotationCommentRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> AnnotationCommentResponse:
    return build_research_items(db=db).update_comment(
        actor=current_user,
        comment_id=comment_id,
        request=request,
    )


@research_router.delete(
    "/annotation-comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_annotation_comment(
    comment_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_research_items(db=db).delete_comment(
        actor=current_user,
        comment_id=comment_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@research_router.patch(
    "/research-items/{item_id}",
    response_model=ResearchItemResponse,
)
def update_research_item(
    item_id: UUID,
    request: ResearchVisibilityRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemResponse:
    return build_research_items(db=db).set_visibility(
        actor=current_user,
        item_id=item_id,
        request=request,
    )


@research_router.delete(
    "/research-items/{item_id}",
    response_model=DeleteResearchItemResponse,
)
def delete_research_item(
    item_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DeleteResearchItemResponse:
    return build_research_items(db=db).delete_item(
        actor=current_user,
        item_id=item_id,
    )
