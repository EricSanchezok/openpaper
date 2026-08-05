"""Conversation domain policies and value objects."""

from .access import (
    ConversationAccessDecision,
    ConversationAccessFacts,
    ConversationReadOnlyReason,
    evaluate_conversation_access,
    require_conversation_continuable,
)

DEFAULT_CONVERSATION_TITLE = "New conversation"

__all__ = [
    "ConversationAccessDecision",
    "ConversationAccessFacts",
    "ConversationReadOnlyReason",
    "DEFAULT_CONVERSATION_TITLE",
    "evaluate_conversation_access",
    "require_conversation_continuable",
]
