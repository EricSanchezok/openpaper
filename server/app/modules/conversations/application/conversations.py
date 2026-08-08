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
    ConversationTurnsResponse,
    ConversationResponseVariantResponse,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
    ConversationToolPermissionsRequest,
    ConversationToolPermissionsResponse,
    PaperContext,
    ConversationTurnResponse,
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
CONVERSATION_RESPONSE_SELECTED = OperationAction("conversation.response_selected")


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

    def turns(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        offset: int,
        limit: int,
    ) -> list[ConversationTurnResponse]: ...

    def select_response(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationResponseVariantResponse: ...

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

    def apply_initial_generated_title(
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
        turn_cursors: SignedCursorCodec,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._turn_cursors = turn_cursors
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

    def turns(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        cursor: str | None,
        limit: int,
    ) -> ConversationTurnsResponse:
        fingerprint = f"{actor.id}:{conversation_id}:{limit}"
        offset = (
            self._turn_cursors.decode(
                cursor=cursor,
                fingerprint=fingerprint,
            )
            if cursor
            else 0
        )
        turns = self._gateway.turns(
            user_id=actor.id,
            conversation_id=conversation_id,
            offset=offset,
            limit=limit + 1,
        )
        has_more = len(turns) > limit
        if has_more:
            # The gateway returns chronological order, so discard the oldest
            # extra item that belongs to the next, older page.
            turns = turns[1:]
        return ConversationTurnsResponse(
            items=turns,
            next_cursor=(
                self._turn_cursors.encode(
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

    def select_response(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        response_id: UUID,
    ) -> ConversationResponseVariantResponse:
        response = self._gateway.select_response(
            user_id=actor.id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            response_id=response_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONVERSATION_RESPONSE_SELECTED,
            resources=(
                ResourceRef("conversation", str(conversation_id)),
                ResourceRef("conversation_turn", str(turn_id)),
                ResourceRef("conversation_response", str(response_id)),
            ),
        )
        return response

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

    def apply_initial_generated_title(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        title: str,
    ) -> None:
        if self._gateway.apply_initial_generated_title(
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
