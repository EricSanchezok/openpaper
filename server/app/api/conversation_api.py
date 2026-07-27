from __future__ import annotations

import uuid

from app.auth.dependencies import get_required_user
from app.database.crud.message_crud import message_crud
from app.database.database import get_db
from app.database.models import ConversableType
from app.database.telemetry import track_event
from app.errors import AppError
from app.llm.conversation_operations import conversation_operations
from app.repositories.conversations import conversation_repository
from app.schemas.conversations import (
    ConversationAutoTitleResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
)
from app.schemas.orm_responses import serialize_messages
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

conversation_router = APIRouter()


@conversation_router.get("", response_model=ConversationListResponse)
def list_conversations(
    archived: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    conversable_type: ConversableType | None = None,
    conversable_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ConversationListResponse:
    if conversable_id is not None and conversable_type is None:
        raise AppError(
            code="conversation_scope_filter_invalid",
            message="conversable_type is required with conversable_id",
            status_code=422,
        )
    if conversable_type == ConversableType.EVERYTHING and conversable_id is not None:
        raise AppError(
            code="conversation_scope_filter_invalid",
            message="Everything conversations do not have conversable_id",
            status_code=422,
        )
    conversations, next_cursor = conversation_repository.list(
        db,
        user_id=current_user.id,
        archived=archived,
        cursor=cursor,
        limit=limit,
        conversable_type=conversable_type,
        conversable_id=conversable_id,
    )
    return ConversationListResponse(
        items=conversation_repository.summarize_many(
            db,
            conversations=conversations,
            user_id=current_user.id,
        ),
        next_cursor=next_cursor,
    )


@conversation_router.post(
    "",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    request: ConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ConversationDetailResponse:
    conversation = conversation_repository.create(
        db, request=request, user_id=current_user.id
    )
    if request.conversable_type == ConversableType.PROJECT:
        track_event(
            "project_conversation_created",
            user_id=str(current_user.id),
            db=db,
        )
    summary = conversation_repository.summarize(db, conversation=conversation)
    return ConversationDetailResponse(**summary.model_dump(), messages=[])


@conversation_router.get(
    "/{conversation_id}", response_model=ConversationDetailResponse
)
def get_conversation(
    conversation_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ConversationDetailResponse:
    conversation = conversation_repository.require_owned(
        db, conversation_id=conversation_id, user_id=current_user.id
    )
    messages = message_crud.get_conversation_messages(
        db,
        conversation_id=conversation_id,
        current_user=current_user,
        page=page,
        page_size=page_size,
    )
    summary = conversation_repository.summarize(db, conversation=conversation)
    return ConversationDetailResponse(
        **summary.model_dump(),
        messages=[dict(message) for message in serialize_messages(messages)],
    )


@conversation_router.patch(
    "/{conversation_id}", response_model=ConversationSummaryResponse
)
def update_conversation(
    conversation_id: uuid.UUID,
    request: ConversationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ConversationSummaryResponse:
    conversation = conversation_repository.update(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        request=request,
    )
    return conversation_repository.summarize(db, conversation=conversation)


@conversation_router.post(
    "/{conversation_id}/move", response_model=ConversationSummaryResponse
)
def move_conversation(
    conversation_id: uuid.UUID,
    request: ConversationMoveRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ConversationSummaryResponse:
    conversation = conversation_repository.move(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        request=request,
    )
    return conversation_repository.summarize(db, conversation=conversation)


@conversation_router.post(
    "/{conversation_id}/detach", response_model=ConversationSummaryResponse
)
def detach_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ConversationSummaryResponse:
    conversation = conversation_repository.move(
        db,
        conversation_id=conversation_id,
        user_id=current_user.id,
        request=ConversationMoveRequest(conversable_type="everything"),
    )
    return conversation_repository.summarize(db, conversation=conversation)


@conversation_router.post(
    "/{conversation_id}/auto-title",
    response_model=ConversationAutoTitleResponse,
)
def auto_title_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ConversationAutoTitleResponse:
    conversation_repository.require_owned(
        db, conversation_id=conversation_id, user_id=current_user.id
    )
    title = conversation_operations.rename_conversation(
        db=db,
        conversation_id=str(conversation_id),
        user=current_user,
    )
    if not title:
        raise AppError(
            code="conversation_title_failed",
            message="Conversation title could not be generated",
            status_code=422,
        )
    return ConversationAutoTitleResponse(title=title)


@conversation_router.delete(
    "/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    conversation_repository.delete(
        db, conversation_id=conversation_id, user_id=current_user.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
