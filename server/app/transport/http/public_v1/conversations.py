"""HTTP adapter for Conversation lifecycle and history."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
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
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Query, Response, status

conversation_router = APIRouter()


@conversation_router.get("", response_model=ConversationListResponse)
def list_conversations(
    archived: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationListResponse:
    return executor.query(
        lambda capabilities: capabilities.conversations.list_page(
            actor=current_user,
            archived=archived,
            cursor=cursor,
            limit=limit,
        )
    )


@conversation_router.post(
    "",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    request: ConversationCreateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationDetailResponse:
    return executor.command(
        lambda capabilities: capabilities.conversations.create(
            actor=current_user,
            request=request,
        )
    )


@conversation_router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation(
    conversation_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationDetailResponse:
    return executor.query(
        lambda capabilities: capabilities.conversations.get(
            actor=current_user,
            conversation_id=conversation_id,
        )
    )


@conversation_router.get(
    "/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
def get_conversation_messages(
    conversation_id: UUID,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationMessagesResponse:
    return executor.query(
        lambda capabilities: capabilities.conversations.messages(
            actor=current_user,
            conversation_id=conversation_id,
            cursor=cursor,
            limit=limit,
        )
    )


@conversation_router.patch(
    "/{conversation_id}",
    response_model=ConversationSummaryResponse,
)
def update_conversation(
    conversation_id: UUID,
    request: ConversationUpdateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationSummaryResponse:
    return executor.command(
        lambda capabilities: capabilities.conversations.update(
            actor=current_user,
            conversation_id=conversation_id,
            request=request,
        )
    )


@conversation_router.put(
    "/{conversation_id}/scope",
    response_model=ConversationSummaryResponse,
)
def move_conversation(
    conversation_id: UUID,
    request: ConversationMoveRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationSummaryResponse:
    return executor.command(
        lambda capabilities: capabilities.conversations.move(
            actor=current_user,
            conversation_id=conversation_id,
            request=request,
        )
    )


@conversation_router.post(
    "/{conversation_id}/title",
    response_model=ConversationAutoTitleResponse,
)
def auto_title_conversation(
    conversation_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ConversationAutoTitleResponse:
    return executor.command(
        lambda capabilities: capabilities.conversations.auto_title(
            actor=current_user,
            conversation_id=conversation_id,
        )
    )


@conversation_router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.conversations.delete(
            actor=current_user,
            conversation_id=conversation_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
