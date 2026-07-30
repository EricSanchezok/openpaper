"""SQLAlchemy, LLM, and telemetry adapters for Conversation use cases."""

from __future__ import annotations

from uuid import UUID

from app.database.models import Conversation
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    ConversationToolPermissionsRequest,
    ConversationToolPermissionsResponse,
    PaperContext,
    MessageResponse,
)
from app.modules.conversations.application.conversations import ConversationChange
from app.modules.conversations.infrastructure.message_repository import (
    message_repository,
)
from app.modules.conversations.infrastructure.presenters import serialize_messages
from app.bootstrap.adapters.conversation_repository import conversation_repository
from sqlalchemy.orm import Session


class SqlAlchemyConversationGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _detail(
        self,
        *,
        conversation: Conversation,
        user_id: int,
    ) -> ConversationDetailResponse:
        summary = conversation_repository.summarize(
            self._db,
            conversation=conversation,
        )
        return ConversationDetailResponse(
            **summary.model_dump(),
            paper_context=conversation_repository.paper_context(
                self._db,
                conversation=conversation,
                user_id=user_id,
            ),
            tool_permissions=conversation_repository.tool_permissions(conversation),
        )

    def list_conversations(
        self,
        *,
        user_id: int,
        archived: bool,
        cursor: str | None,
        limit: int,
    ) -> ConversationListResponse:
        conversations, next_cursor = conversation_repository.list(
            self._db,
            user_id=user_id,
            archived=archived,
            cursor=cursor,
            limit=limit,
        )
        return ConversationListResponse(
            items=[
                conversation_repository.summarize(
                    self._db,
                    conversation=conversation,
                )
                for conversation in conversations
            ],
            next_cursor=next_cursor,
        )

    def create(
        self,
        *,
        user_id: int,
        request: ConversationCreateRequest,
    ) -> ConversationDetailResponse:
        conversation = conversation_repository.create(
            self._db,
            request=request,
            user_id=user_id,
        )
        return self._detail(conversation=conversation, user_id=user_id)

    def get(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
    ) -> ConversationDetailResponse:
        conversation = conversation_repository.require_owned(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return self._detail(conversation=conversation, user_id=user_id)

    def messages(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        offset: int,
        limit: int,
    ) -> list[MessageResponse]:
        return serialize_messages(
            message_repository.list_conversation_messages(
                self._db,
                conversation_id=conversation_id,
                user_id=user_id,
                offset=offset,
                limit=limit,
            )
        )

    def update(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationUpdateRequest,
    ) -> ConversationChange[ConversationSummaryResponse]:
        result = conversation_repository.update(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(
            value=conversation_repository.summarize(
                self._db,
                conversation=result.value,
            ),
            changed=result.changed,
        )

    def move(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationChange[ConversationSummaryResponse]:
        result = conversation_repository.move(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(
            value=conversation_repository.summarize(
                self._db,
                conversation=result.value,
            ),
            changed=result.changed,
        )

    def delete(self, *, user_id: int, conversation_id: UUID) -> None:
        conversation_repository.delete(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    def update_paper_context(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: PaperContext,
    ) -> ConversationChange[PaperContext]:
        result = conversation_repository.update_paper_context(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(value=result.value, changed=result.changed)

    def update_tool_permissions(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationToolPermissionsRequest,
    ) -> ConversationChange[ConversationToolPermissionsResponse]:
        result = conversation_repository.update_tool_permissions(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return ConversationChange(value=result.value, changed=result.changed)

    def update_title(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        title: str,
    ) -> bool:
        return conversation_repository.update(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=ConversationUpdateRequest(title=title),
        ).changed
