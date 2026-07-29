"""Map conversation ORM projections into application response contracts."""

from app.modules.conversations.application.contracts.conversations import (
    MessageResponse,
)
from app.modules.conversations.infrastructure.models import Message


def serialize_messages(messages: list[Message]) -> list[MessageResponse]:
    return [
        MessageResponse.model_validate(
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "references": message.references,
                "artifacts": [
                    item.citation.snapshot
                    for item in message.research_items
                    if item.citation is not None
                ]
                or None,
                "trace": message.trace,
                "scope": message.scope,
                "sequence": message.sequence,
            }
        )
        for message in messages
    ]
