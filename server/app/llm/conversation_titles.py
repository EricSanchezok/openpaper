"""Conversation title generation."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.llm.backend import HistoryMessage, TextContent
from app.llm.base import BaseLLMClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You summarize conversations as concise, descriptive titles. Return plain text
only, using no more than five words, and reflect the conversation's main topic.
""".strip()

_USER_PROMPT = """
Generate a title for this conversation:

{chat_history}

Title:
""".strip()


def should_generate_initial_title(
    *,
    title_is_default: bool,
    chat_history: Sequence[HistoryMessage],
) -> bool:
    """Generate once, immediately after the first successful assistant reply."""
    return (
        title_is_default
        and sum(message.role == "assistant" for message in chat_history) == 1
    )


class InitialConversationTitleGenerator(BaseLLMClient):
    def generate(
        self,
        chat_history: Sequence[HistoryMessage],
    ) -> str | None:
        if not chat_history:
            return None
        formatted_history = "\n".join(
            f"{message.role}: {message.content}" for message in chat_history[-4:]
        )
        response = self.generate_content(
            contents=[
                TextContent(
                    text=_USER_PROMPT.format(chat_history=formatted_history),
                )
            ],
            system_prompt=_SYSTEM_PROMPT,
        )
        if response and response.text:
            return response.text.strip()
        logger.error("conversation.title_generation.failed")
        return None


initial_conversation_title_generator = InitialConversationTitleGenerator()
