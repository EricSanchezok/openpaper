"""Conversation lifecycle and history use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    ConversationToolPermissionsRequest,
    ConversationToolPermissionsResponse,
    PaperContext,
    MessageResponse,
)
from app.shared.application import Actor, OperationContext, SignedCursorCodec

CONVERSATION_CREATED = OperationAction("conversation.created")
CONVERSATION_UPDATED = OperationAction("conversation.updated")
CONVERSATION_MOVED = OperationAction("conversation.moved")
CONVERSATION_TITLE_UPDATED = OperationAction("conversation.title_updated")
CONVERSATION_DELETED = OperationAction("conversation.deleted")
CONVERSATION_PAPER_CONTEXT_UPDATED = OperationAction(
    "conversation.paper_context_updated"
)
CONVERSATION_TOOL_PERMISSIONS_UPDATED = OperationAction(
    "conversation.tool_permissions_updated"
)


@dataclass(frozen=True, slots=True)
class ConversationChange[T]:
    value: T
    changed: bool


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
    ) -> ConversationChange[ConversationSummaryResponse]: ...

    def move(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationChange[ConversationSummaryResponse]: ...

    def delete(self, *, user_id: int, conversation_id: UUID) -> None: ...

    def update_paper_context(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: PaperContext,
    ) -> ConversationChange[PaperContext]: ...

    def update_tool_permissions(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        request: ConversationToolPermissionsRequest,
    ) -> ConversationChange[ConversationToolPermissionsResponse]: ...

    def update_title(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        title: str,
    ) -> bool: ...


class Conversations:
    def __init__(
        self,
        *,
        gateway: ConversationGateway,
        message_cursors: SignedCursorCodec,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._message_cursors = message_cursors
        self._journal = journal

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
        operation: OperationContext,
        request: ConversationCreateRequest,
    ) -> ConversationDetailResponse:
        result = self._gateway.create(user_id=actor.id, request=request)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONVERSATION_CREATED,
            resources=(ResourceRef("conversation", str(result.id)),),
        )
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
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationUpdateRequest,
    ) -> ConversationSummaryResponse:
        result = self._gateway.update(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value

    def move(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationMoveRequest,
    ) -> ConversationSummaryResponse:
        result = self._gateway.move(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_MOVED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value

    def apply_generated_title(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        title: str,
    ) -> None:
        if self._gateway.update_title(
            user_id=actor.id,
            conversation_id=conversation_id,
            title=title,
        ):
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_TITLE_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )

    def delete(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
    ) -> None:
        self._gateway.delete(
            user_id=actor.id,
            conversation_id=conversation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONVERSATION_DELETED,
            resources=(ResourceRef("conversation", str(conversation_id)),),
        )

    def update_paper_context(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: PaperContext,
    ) -> PaperContext:
        result = self._gateway.update_paper_context(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_PAPER_CONTEXT_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value

    def update_tool_permissions(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationToolPermissionsRequest,
    ) -> ConversationToolPermissionsResponse:
        result = self._gateway.update_tool_permissions(
            user_id=actor.id,
            conversation_id=conversation_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_TOOL_PERMISSIONS_UPDATED,
                resources=(ResourceRef("conversation", str(conversation_id)),),
            )
        return result.value
