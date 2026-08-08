"""Short-transaction workflow for response follow-up suggestions."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.conversations.application.contracts.conversations import (
    ConversationSuggestionsResponse,
)
from app.modules.conversations.application.suggestions import (
    SuggestionClaim,
    SuggestionSeed,
)
from app.shared.application import Actor, ApplicationExecutor

logger = logging.getLogger(__name__)


class ConversationSuggestionGenerator(Protocol):
    async def generate(self, seed: SuggestionSeed) -> list[str]: ...


def _response(claim: SuggestionClaim) -> ConversationSuggestionsResponse:
    return ConversationSuggestionsResponse(
        response_id=claim.response_id,
        status=claim.status,
        suggestions=list(claim.suggestions),
    )


def _validated_suggestions(values: list[str]) -> tuple[str, str, str]:
    normalized = [" ".join(value.split()).strip() for value in values]
    if (
        len(normalized) != 3
        or any(not value or len(value) > 160 for value in normalized)
        or len({value.casefold() for value in normalized}) != 3
    ):
        raise ValueError("suggestion generator must return three unique values")
    return normalized[0], normalized[1], normalized[2]


class ConversationSuggestionWorkflow:
    """Claim, generate outside a transaction, then atomically finalize."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        generator: ConversationSuggestionGenerator,
    ) -> None:
        self._executor = executor
        self._generator = generator

    async def generate(
        self,
        *,
        actor: Actor,
        conversation_id: UUID,
        response_id: UUID,
    ) -> ConversationSuggestionsResponse:
        claim = await asyncio.to_thread(
            self._executor.command,
            lambda capabilities: capabilities.conversation_suggestions.claim(
                actor=actor,
                conversation_id=conversation_id,
                response_id=response_id,
            ),
        )
        if claim.seed is None:
            return _response(claim)

        try:
            suggestions = _validated_suggestions(
                await self._generator.generate(claim.seed)
            )
        except Exception as exc:
            logger.warning(
                "conversation.suggestions.generation_failed",
                extra={
                    "response_id": str(response_id),
                    "error_type": type(exc).__name__,
                },
            )
            failed = await asyncio.to_thread(
                self._executor.command,
                lambda capabilities: capabilities.conversation_suggestions.fail(
                    actor=actor,
                    conversation_id=conversation_id,
                    response_id=response_id,
                ),
            )
            return _response(failed)

        completed = await asyncio.to_thread(
            self._executor.command,
            lambda capabilities: capabilities.conversation_suggestions.complete(
                actor=actor,
                conversation_id=conversation_id,
                response_id=response_id,
                suggestions=suggestions,
            ),
        )
        return _response(completed)


__all__ = [
    "ConversationSuggestionGenerator",
    "ConversationSuggestionWorkflow",
]
