"""HTTP adapter for Conversation lifecycle and history."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_conversations
from app.bootstrap.settings import AppSettings
from app.database.database import get_db
from app.modules.conversations.application.contracts.conversations import (
    ConversationAutoTitleResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
)
from app.modules.conversations.application.conversations import Conversations
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

conversation_router = APIRouter()


def _conversations(request: Request, db: Session) -> Conversations:
    settings: AppSettings = request.app.state.settings
    return build_conversations(
        db=db,
        cursor_secret=settings.paper_search_cursor_secret,
    )


@conversation_router.get("", response_model=ConversationListResponse)
def list_conversations(
    request: Request,
    archived: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ConversationListResponse:
    return _conversations(request, db).list_page(
        actor=current_user,
        archived=archived,
        cursor=cursor,
        limit=limit,
    )


@conversation_router.post(
    "",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    request: ConversationCreateRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ConversationDetailResponse:
    return _conversations(http_request, db).create(
        actor=current_user,
        request=request,
    )


@conversation_router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation(
    conversation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ConversationDetailResponse:
    return _conversations(request, db).get(
        actor=current_user,
        conversation_id=conversation_id,
    )


@conversation_router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
def get_conversation_messages(
    conversation_id: UUID,
    request: Request,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ConversationMessagesResponse:
    return _conversations(request, db).messages(
        actor=current_user,
        conversation_id=conversation_id,
        cursor=cursor,
        limit=limit,
    )


@conversation_router.patch(
    "/{conversation_id}",
    response_model=ConversationSummaryResponse,
)
def update_conversation(
    conversation_id: UUID,
    request: ConversationUpdateRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ConversationSummaryResponse:
    return _conversations(http_request, db).update(
        actor=current_user,
        conversation_id=conversation_id,
        request=request,
    )


@conversation_router.put(
    "/{conversation_id}/scope",
    response_model=ConversationSummaryResponse,
)
def move_conversation(
    conversation_id: UUID,
    request: ConversationMoveRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ConversationSummaryResponse:
    return _conversations(http_request, db).move(
        actor=current_user,
        conversation_id=conversation_id,
        request=request,
    )


@conversation_router.post(
    "/{conversation_id}/title",
    response_model=ConversationAutoTitleResponse,
)
def auto_title_conversation(
    conversation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ConversationAutoTitleResponse:
    return _conversations(request, db).auto_title(
        actor=current_user,
        conversation_id=conversation_id,
    )


@conversation_router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    _conversations(request, db).delete(
        actor=current_user,
        conversation_id=conversation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
