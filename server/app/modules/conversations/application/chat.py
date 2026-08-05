"""Conversation message use case and replaceable streaming boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
    ConversationTrace,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)
from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import Actor, OperationContext
from app.shared.domain import JsonValue, WorkspacePermission
from app.shared.domain.enums import ConversationScopeType
from app.shared.domain.enums import ReasoningLevel

CONVERSATION_MESSAGE_CREATED = OperationAction("conversation.message_created")
RESEARCH_CITATION_CREATED = OperationAction("research.citation_created")


@dataclass(frozen=True, slots=True)
class ChatHistoryMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ChatPaperSnapshot:
    document_id: UUID
    title: str | None
    abstract: str | None
    raw_content: str | None
    keywords: list[str] | None
    authors: list[str] | None
    publish_date: date | datetime | None


@dataclass(frozen=True, slots=True)
class ConversationChatScope:
    scope_type: ConversationScopeType
    project_id: UUID | None
    document_id: UUID | None
    paper_context: PaperCollection
    tool_permissions: frozenset[WorkspacePermission]


@dataclass(frozen=True, slots=True)
class MentionScope:
    snapshot: list[dict[str, JsonValue]] | None
    highlights: list[dict[str, JsonValue]] | None


@dataclass(frozen=True, slots=True)
class ChatProjectSnapshot:
    project_id: UUID
    title: str
    description: str | None
    document_count: int


@dataclass(frozen=True, slots=True)
class ConversationContextSnapshot:
    papers: list[ChatPaperSnapshot]
    projects: list[ChatProjectSnapshot]
    available_document_count: int | None


@dataclass(frozen=True, slots=True)
class PersistedChatMessage:
    id: UUID
    turn_id: UUID
    content: str
    references: dict[str, JsonValue] | None
    trace: ConversationTrace | None


@dataclass(frozen=True, slots=True)
class ConversationTurnStart:
    user_message_id: UUID
    user_operation_id: UUID
    correlation_id: UUID
    created: bool
    assistant: PersistedChatMessage | None


@dataclass(frozen=True, slots=True)
class ConversationTurnCompletion:
    assistant: PersistedChatMessage
    created: bool
    citation_ids: tuple[UUID, ...]


class ConversationChatDataGateway(Protocol):
    def prepare(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
    ) -> ConversationChatScope: ...

    def history(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        exclude_turn_id: UUID | None,
    ) -> list[ChatHistoryMessage]: ...

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot: ...

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationMessageRequest,
    ) -> MentionScope: ...

    def start_turn(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        user_content: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
        created_operation_id: UUID,
        correlation_id: UUID,
    ) -> ConversationTurnStart: ...

    def complete_turn(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        turn_id: UUID,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: ConversationTrace | None,
        artifacts: list[dict[str, JsonValue]],
        created_operation_id: UUID,
        correlation_id: UUID,
    ) -> ConversationTurnCompletion: ...


class ConversationChatData:
    """Short-transaction persistence boundary used by the streaming workflow."""

    def __init__(
        self,
        gateway: ConversationChatDataGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def prepare(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
    ) -> ConversationChatScope:
        return self._gateway.prepare(actor=actor, conversation_id=conversation_id)

    def history(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        exclude_turn_id: UUID | None = None,
    ) -> list[ChatHistoryMessage]:
        return self._gateway.history(
            actor=actor,
            conversation_id=conversation_id,
            exclude_turn_id=exclude_turn_id,
        )

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot:
        return self._gateway.context(actor=actor, scope=scope)

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationMessageRequest,
    ) -> MentionScope:
        return self._gateway.mentions(
            actor=actor,
            request=request,
        )

    def start_turn(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        user_content: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
    ) -> ConversationTurnStart:
        result = self._gateway.start_turn(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            user_content=user_content,
            user_references=user_references,
            scope=scope,
            created_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        if result.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_MESSAGE_CREATED,
                resources=(
                    ResourceRef("conversation", str(conversation_id)),
                    ResourceRef("message", str(result.user_message_id)),
                ),
            )
        return result

    def complete_turn(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        turn_id: UUID,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: ConversationTrace | None,
        artifacts: list[dict[str, JsonValue]],
    ) -> ConversationTurnCompletion:
        result = self._gateway.complete_turn(
            actor=actor,
            conversation_id=conversation_id,
            turn_id=turn_id,
            assistant_content=assistant_content,
            assistant_references=assistant_references,
            assistant_trace=assistant_trace,
            artifacts=artifacts,
            created_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        if result.created:
            changes = [
                OperationChange(
                    action=CONVERSATION_MESSAGE_CREATED,
                    resources=(
                        ResourceRef("conversation", str(conversation_id)),
                        ResourceRef("message", str(result.assistant.id)),
                    ),
                )
            ]
            changes.extend(
                OperationChange(
                    action=RESEARCH_CITATION_CREATED,
                    resources=(ResourceRef("research_item", str(citation_id)),),
                )
                for citation_id in result.citation_ids
            )
            self._journal.append_many(
                actor=actor,
                operation=operation,
                changes=changes,
            )
        return result


class ConversationChatGateway(Protocol):
    async def stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationMessageRequest,
        client_ip: str,
    ) -> AsyncIterator[str]: ...


class ConversationChat:
    def __init__(self, gateway: ConversationChatGateway) -> None:
        self._gateway = gateway

    async def stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: UUID,
        request: ConversationMessageRequest,
        client_ip: str,
    ) -> AsyncIterator[str]:
        return await self._gateway.stream(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            request=request,
            client_ip=client_ip,
        )

    @staticmethod
    def capabilities() -> dict[str, object]:
        return {
            "reasoning_levels": [
                {
                    "id": ReasoningLevel.STANDARD.value,
                    "label": "Standard",
                    "description": ("Fast, balanced reasoning for most questions."),
                },
                {
                    "id": ReasoningLevel.DEEP.value,
                    "label": "Deep",
                    "description": ("More thorough reasoning for complex questions."),
                },
            ],
            "default_reasoning_level": ReasoningLevel.STANDARD.value,
        }
