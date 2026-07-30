"""Conversation message use case and replaceable streaming boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
)
from app.modules.conversations.application.contracts.conversations import (
    PaperContext,
)
from app.shared.application import Actor
from app.shared.domain import JsonValue
from app.shared.domain.enums import ConversationScopeType
from app.shared.domain.enums import ReasoningLevel


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
    paper_context: PaperContext


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
    ) -> list[ChatHistoryMessage]: ...

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot: ...

    def context_contains_document(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
        document_id: UUID,
    ) -> bool: ...

    def mentions(
        self,
        *,
        actor: Actor,
        request: ConversationMessageRequest,
    ) -> MentionScope: ...

    def save_turn(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        user_content: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: dict[str, JsonValue] | None,
        artifacts: list[dict[str, JsonValue]],
    ) -> None: ...

    def rename(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        title: str,
    ) -> None: ...


class ConversationChatData:
    """Short-transaction persistence boundary used by the streaming workflow."""

    def __init__(self, gateway: ConversationChatDataGateway) -> None:
        self._gateway = gateway

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
    ) -> list[ChatHistoryMessage]:
        return self._gateway.history(actor=actor, conversation_id=conversation_id)

    def context(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
    ) -> ConversationContextSnapshot:
        return self._gateway.context(actor=actor, scope=scope)

    def context_contains_document(
        self,
        *,
        actor: Actor,
        scope: ConversationChatScope,
        document_id: UUID,
    ) -> bool:
        return self._gateway.context_contains_document(
            actor=actor,
            scope=scope,
            document_id=document_id,
        )

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

    def save_turn(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        user_content: str,
        user_references: dict[str, JsonValue] | None,
        scope: list[dict[str, JsonValue]] | None,
        assistant_content: str,
        assistant_references: dict[str, JsonValue] | None,
        assistant_trace: dict[str, JsonValue] | None,
        artifacts: list[dict[str, JsonValue]],
    ) -> None:
        self._gateway.save_turn(
            actor=actor,
            conversation_id=conversation_id,
            user_content=user_content,
            user_references=user_references,
            scope=scope,
            assistant_content=assistant_content,
            assistant_references=assistant_references,
            assistant_trace=assistant_trace,
            artifacts=artifacts,
        )

    def rename(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        title: str,
    ) -> None:
        self._gateway.rename(
            actor=actor,
            conversation_id=conversation_id,
            title=title,
        )


class ConversationChatGateway(Protocol):
    async def stream(
        self,
        *,
        actor: Actor,
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
        conversation_id: UUID,
        request: ConversationMessageRequest,
        client_ip: str,
    ) -> AsyncIterator[str]:
        return await self._gateway.stream(
            actor=actor,
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
