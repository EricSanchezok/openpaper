"""HTTP streaming endpoints for conversation turns and response variants."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.execution import (
    get_conversation_chat,
    get_operation_context_factory,
)
from app.modules.conversations.application.chat import ConversationChat
from app.modules.conversations.application.contracts.turns import (
    ConversationResponseCreateRequest,
    ConversationStreamEventSchema,
    ConversationTurnCreateRequest,
)
from app.shared.application import (
    Actor,
    ConversationOrigin,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.transport.client_ip import http_client_ip
from app.transport.http.observability import attach_operation_context
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

turn_router = APIRouter()


class ConversationEventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


def _stream_responses() -> dict[int | str, dict[str, object]]:
    return {
        200: {
            "description": "Standard SSE stream of typed conversation events.",
            "model": ConversationStreamEventSchema,
            "content": {
                "text/event-stream": {
                    "schema": {
                        "$ref": "#/components/schemas/ConversationStreamEventSchema"
                    }
                }
            },
        }
    }


def _conversation_operation(
    *,
    conversation_id: UUID,
    turn_id: UUID,
    request_operation: OperationContext,
    operation_factory: OperationContextFactory,
) -> OperationContext:
    if not isinstance(request_operation.origin, HttpOrigin):
        raise RuntimeError("conversation_http_origin_missing")
    return operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=request_operation.origin.request,
            conversation_id=conversation_id,
            turn_id=turn_id,
        ),
        credential=request_operation.credential,
    )


@turn_router.get("/capabilities")
def get_chat_capabilities(
    chat: ConversationChat = Depends(get_conversation_chat),
) -> dict[str, object]:
    return chat.capabilities()


@turn_router.post(
    "/{conversation_id}/turns",
    response_class=ConversationEventStreamResponse,
    responses=_stream_responses(),
)
async def create_conversation_turn(
    conversation_id: UUID,
    turn: ConversationTurnCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
) -> ConversationEventStreamResponse:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=turn.turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    stream = await chat.stream(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        request=turn,
        client_ip=http_client_ip(http_request),
    )
    return ConversationEventStreamResponse(stream)


@turn_router.post(
    "/{conversation_id}/turns/{turn_id}/responses",
    response_class=ConversationEventStreamResponse,
    responses=_stream_responses(),
)
async def retry_conversation_turn(
    conversation_id: UUID,
    turn_id: UUID,
    response: ConversationResponseCreateRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
) -> ConversationEventStreamResponse:
    operation = _conversation_operation(
        conversation_id=conversation_id,
        turn_id=turn_id,
        request_operation=request_operation,
        operation_factory=operation_factory,
    )
    attach_operation_context(http_request, operation, actor_id=str(current_user.id))
    stream = await chat.retry(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        turn_id=turn_id,
        response_id=response.response_id,
        client_ip=http_client_ip(http_request),
    )
    return ConversationEventStreamResponse(stream)
