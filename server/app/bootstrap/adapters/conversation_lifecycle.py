"""SQLAlchemy, LLM, and telemetry adapters for Conversation use cases."""

from __future__ import annotations

from uuid import UUID

from app.database.telemetry import track_event
from app.llm.conversation_operations import conversation_operations
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    PaperContext,
    MessageResponse,
)
from app.modules.conversations.infrastructure.message_repository import (
    message_repository,
)
from app.modules.conversations.infrastructure.presenters import serialize_messages
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.shared.application import Actor
from app.shared.domain.enums import ConversationScopeType
from sqlalchemy.orm import Session


class SqlAlchemyConversationGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

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
        )

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
        )

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
    ) -> ConversationSummaryResponse:
        conversation = conversation_repository.update(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return conversation_repository.summarize(
            self._db,
            conversation=conversation,
        )

    def move(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationSummaryResponse:
        conversation = conversation_repository.move(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )
        return conversation_repository.summarize(
            self._db,
            conversation=conversation,
        )

    def require_owned(self, *, user_id: int, conversation_id: UUID) -> None:
        conversation_repository.require_owned(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
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
    ) -> PaperContext:
        return conversation_repository.update_paper_context(
            self._db,
            conversation_id=conversation_id,
            user_id=user_id,
            request=request,
        )


class LlmConversationTitleGenerator:
    def __init__(self, db: Session) -> None:
        self._db = db

    def generate(self, *, actor: Actor, conversation_id: UUID) -> str | None:
        return conversation_operations.rename_conversation(
            db=self._db,
            conversation_id=str(conversation_id),
            user=actor,
        )


class PostHogConversationEvents:
    def __init__(self, db: Session) -> None:
        self._db = db

    def created(self, *, actor: Actor, scope_type: ConversationScopeType) -> None:
        if scope_type == ConversationScopeType.PROJECT:
            track_event(
                "project_conversation_created",
                user_id=str(actor.id),
                db=self._db,
            )
