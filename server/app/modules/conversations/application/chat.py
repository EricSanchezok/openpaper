"""Conversation message use case and replaceable streaming boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
)
from app.shared.application import Actor
from app.shared.domain.enums import ReasoningLevel


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
