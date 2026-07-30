"""Conversation lifecycle and history use cases."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.conversations.application.contracts.conversations import (
    ConversationAutoTitleResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    PaperContext,
    MessageResponse,
)
from app.shared.application import Actor, SignedCursorCodec
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ConversationScopeType


class ConversationGateway(Protocol):
    def list_conversations(
        self,
        *,
        user_id: int,
        archived: bool,
        cursor: str | None,
        limit: int,
    ) -> ConversationListResponse: ...

    def create(
        self,
        *,
        user_id: int,
        request: ConversationCreateRequest,
    ) -> ConversationDetailResponse: ...

    def get(
        self, *, user_id: int, conversation_id: UUID
    ) -> ConversationDetailResponse: ...

    def messages(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        offset: int,
        limit: int,
    ) -> list[MessageResponse]: ...

    def update(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationUpdateRequest,
    ) -> ConversationSummaryResponse: ...

    def move(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationSummaryResponse: ...

    def require_owned(self, *, user_id: int, conversation_id: UUID) -> None: ...

    def delete(self, *, user_id: int, conversation_id: UUID) -> None: ...

    def update_paper_context(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: PaperContext,
    ) -> PaperContext: ...


class ConversationTitleGenerator(Protocol):
    def generate(self, *, actor: Actor, conversation_id: UUID) -> str | None: ...


class ConversationEvents(Protocol):
    def created(self, *, actor: Actor, scope_type: ConversationScopeType) -> None: ...


class Conversations:
    def __init__(
        self,
        *,
        gateway: ConversationGateway,
        titles: ConversationTitleGenerator,
        events: ConversationEvents,
        message_cursors: SignedCursorCodec,
    ) -> None:
        self._gateway = gateway
        self._titles = titles
        self._events = events
        self._message_cursors = message_cursors

    def list_page(
        self,
        *,
        actor: Actor,
        archived: bool,
        cursor: str | None,
        limit: int,
    ) -> ConversationListResponse:
        return self._gateway.list_conversations(
            user_id=actor.id,
            archived=archived,
            cursor=cursor,
            limit=limit,
        )

    def create(
        self,
        *,
        actor: Actor,
        request: ConversationCreateRequest,
    ) -> ConversationDetailResponse:
        result = self._gateway.create(user_id=actor.id, request=request)
        self._events.created(actor=actor, scope_type=request.scope_type)
        return result

    def get(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
    ) -> ConversationDetailResponse:
        return self._gateway.get(
            user_id=actor.id,
            conversation_id=conversation_id,
        )

    def messages(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> ConversationMessagesResponse:
        fingerprint = f"{actor.id}:{conversation_id}:{limit}"
        offset = (
            self._message_cursors.decode(
                cursor=cursor,
                fingerprint=fingerprint,
            )
            if cursor
            else 0
        )
        messages = self._gateway.messages(
            user_id=actor.id,
            conversation_id=conversation_id,
            offset=offset,
            limit=limit + 1,
        )
        has_more = len(messages) > limit
        if has_more:
            # The gateway returns chronological order, so discard the oldest
            # extra item that belongs to the next, older page.
            messages = messages[1:]
        return ConversationMessagesResponse(
            items=messages,
            next_cursor=(
                self._message_cursors.encode(
                    fingerprint=fingerprint,
                    offset=offset + limit,
                )
                if has_more
                else None
            ),
        )

    def update(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        request: ConversationUpdateRequest,
    ) -> ConversationSummaryResponse:
        return self._gateway.update(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )

    def move(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationSummaryResponse:
        return self._gateway.move(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )

    def auto_title(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
    ) -> ConversationAutoTitleResponse:
        self._gateway.require_owned(
            user_id=actor.id,
            conversation_id=conversation_id,
        )
        title = self._titles.generate(
            actor=actor,
            conversation_id=conversation_id,
        )
        if not title:
            raise AppError(
                code="conversation_title_failed",
                message="Conversation title could not be generated",
                kind=FailureKind.UNPROCESSABLE,
            )
        return ConversationAutoTitleResponse(title=title)

    def delete(self, *, actor: Actor, conversation_id: UUID) -> None:
        self._gateway.delete(
            user_id=actor.id,
            conversation_id=conversation_id,
        )

    def update_paper_context(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        request: PaperContext,
    ) -> PaperContext:
        return self._gateway.update_paper_context(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
