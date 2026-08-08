"""Map conversation ORM projections into application response contracts."""

from uuid import UUID

from app.modules.conversations.application.contracts.conversations import (
    ConversationResponseVariantResponse,
    ConversationTurnResponse,
)
from app.modules.conversations.infrastructure.models import (
    ConversationResponse,
    ConversationTurn,
)


def serialize_response(
    response: ConversationResponse,
) -> ConversationResponseVariantResponse:
    return ConversationResponseVariantResponse.model_validate(
        {
            "id": response.id,
            "variant_index": response.variant_index,
            "status": response.status,
            "content": response.content,
            "references": response.references,
            "artifacts": [
                item.citation.snapshot
                for item in response.research_items
                if item.citation is not None
            ]
            or None,
            "trace": response.trace,
            "suggestions": response.suggestions,
            "suggestions_status": response.suggestions_status,
        }
    )


def serialize_turns(
    turns: list[ConversationTurn], *, latest_turn_id: UUID | None
) -> list[ConversationTurnResponse]:
    result: list[ConversationTurnResponse] = []
    for turn in turns:
        visible = (
            [response for response in turn.responses if response.status == "completed"]
            if turn.id == latest_turn_id
            else [
                response
                for response in turn.responses
                if response.id == turn.selected_response_id
            ]
        )
        responses = [serialize_response(response) for response in visible]
        result.append(
            ConversationTurnResponse.model_validate(
                {
                    "id": turn.id,
                    "user_query": turn.user_query,
                    "user_references": turn.user_references,
                    "scope": turn.scope,
                    "reasoning_level": turn.reasoning_level,
                    "locale": turn.locale,
                    "time_zone": turn.time_zone,
                    "sequence": turn.sequence,
                    "selected_response_id": turn.selected_response_id,
                    "responses": responses,
                }
            )
        )
    return result
