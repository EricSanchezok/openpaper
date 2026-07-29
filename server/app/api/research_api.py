"""Public API for typed, scope-aware research items."""

from __future__ import annotations

from uuid import UUID

from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.database import get_db
from app.database.models import ResearchItemKind
from app.modules.research.infrastructure.repository import (
    HighlightThreadCreate,
    research_repository,
)
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
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

document_research_router = APIRouter()
project_research_router = APIRouter()
research_router = APIRouter()


def _serialize(
    db: Session,
    *,
    item: object,
    user_id: int,
) -> ResearchItemResponse:
    from app.database.models import ResearchItem

    if not isinstance(item, ResearchItem):
        raise TypeError("expected ResearchItem")
    return research_repository.serialize(db, item=item, user_id=user_id)


@document_research_router.get(
    "/{document_id}/research-items",
    response_model=ResearchItemListResponse,
)
def list_document_research_items(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemListResponse:
    items = research_repository.list_for_document(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    return ResearchItemListResponse(
        items=[_serialize(db, item=item, user_id=current_user.id) for item in items]
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
    items = research_repository.list_for_project(
        db,
        project_id=project_id,
        user_id=current_user.id,
    )
    return ResearchItemListResponse(
        items=[_serialize(db, item=item, user_id=current_user.id) for item in items]
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
    items = research_repository.list_for_document(
        db,
        document_id=document_id,
        user_id=current_user.id,
        kind=ResearchItemKind.HIGHLIGHT_THREAD,
    )
    return ResearchItemListResponse(
        items=[_serialize(db, item=item, user_id=current_user.id) for item in items]
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
    item = research_repository.create_highlight_thread(
        db,
        document_id=document_id,
        user_id=current_user.id,
        create=HighlightThreadCreate(
            quote_text=request.quote_text,
            page_number=request.page_number,
            start_offset=request.start_offset,
            end_offset=request.end_offset,
            position=request.position,
            color=request.color,
            is_shared=request.shared,
        ),
    )
    return _serialize(db, item=item, user_id=current_user.id)


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
    values = request.model_dump(exclude_unset=True)
    item = research_repository.update_highlight_thread(
        db,
        thread_id=thread_id,
        user_id=current_user.id,
        values=values,
    )
    return _serialize(db, item=item, user_id=current_user.id)


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
    research_repository.delete_item(
        db,
        item_id=thread_id,
        user_id=current_user.id,
        confirm_delete_replies=request.confirm_delete_replies,
    )
    return DeleteResearchItemResponse()


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
    comment = research_repository.add_comment(
        db,
        thread_id=thread_id,
        user_id=current_user.id,
        content=request.content,
    )
    return research_repository.serialize_comment(
        comment,
        user_id=current_user.id,
        has_scope_access=True,
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
    comment = research_repository.update_comment(
        db,
        comment_id=comment_id,
        user_id=current_user.id,
        content=request.content,
    )
    return research_repository.serialize_comment(
        comment,
        user_id=current_user.id,
        has_scope_access=True,
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
    research_repository.delete_comment(
        db,
        comment_id=comment_id,
        user_id=current_user.id,
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
    item = research_repository.set_visibility(
        db,
        item_id=item_id,
        user_id=current_user.id,
        shared=request.shared,
    )
    return _serialize(db, item=item, user_id=current_user.id)


@research_router.delete(
    "/research-items/{item_id}",
    response_model=DeleteResearchItemResponse,
)
def delete_research_item(
    item_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DeleteResearchItemResponse:
    research_repository.delete_item(
        db,
        item_id=item_id,
        user_id=current_user.id,
    )
    return DeleteResearchItemResponse()
