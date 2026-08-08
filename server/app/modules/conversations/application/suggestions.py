"""Conversation response follow-up suggestion contracts and data capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from app.shared.application import Actor

SuggestionStatus = Literal["pending", "completed", "failed"]


@dataclass(frozen=True, slots=True)
class SuggestionSeed:
    response_id: UUID
    user_query: str
    final_answer: str
    locale: Literal["en", "zh-CN"]
    source_titles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SuggestionClaim:
    response_id: UUID
    status: SuggestionStatus
    suggestions: tuple[str, ...] = ()
    seed: SuggestionSeed | None = None


class ConversationSuggestionGateway(Protocol):
    def claim(
        self, *, user_id: int, conversation_id: UUID, response_id: UUID
    ) -> SuggestionClaim: ...

    def complete(
        self,
        *,
        user_id: int,
        conversation_id: UUID,
        response_id: UUID,
        suggestions: tuple[str, str, str],
    ) -> SuggestionClaim: ...

    def fail(
        self, *, user_id: int, conversation_id: UUID, response_id: UUID
    ) -> SuggestionClaim: ...


class ConversationSuggestionsData:
    """Session-bound persistence operations for the asynchronous workflow."""

    def __init__(self, gateway: ConversationSuggestionGateway) -> None:
        self._gateway = gateway

    def claim(
        self, *, actor: Actor, conversation_id: UUID, response_id: UUID
    ) -> SuggestionClaim:
        return self._gateway.claim(
            user_id=actor.id,
            conversation_id=conversation_id,
            response_id=response_id,
        )

    def complete(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        response_id: UUID,
        suggestions: tuple[str, str, str],
    ) -> SuggestionClaim:
        return self._gateway.complete(
            user_id=actor.id,
            conversation_id=conversation_id,
            response_id=response_id,
            suggestions=suggestions,
        )

    def fail(
        self, *, actor: Actor, conversation_id: UUID, response_id: UUID
    ) -> SuggestionClaim:
        return self._gateway.fail(
            user_id=actor.id,
            conversation_id=conversation_id,
            response_id=response_id,
        )
