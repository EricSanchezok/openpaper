import uuid

from app.bootstrap.execution import (
    get_conversation_chat,
    get_operation_context_factory,
)
from app.modules.conversations.application.chat import ConversationChat
from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
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
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from app.transport.http.observability import attach_operation_context
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

message_router = APIRouter()


@message_router.get("/capabilities")
def get_chat_capabilities(
    chat: ConversationChat = Depends(get_conversation_chat),
) -> dict[str, object]:
    return chat.capabilities()


@message_router.post("/{conversation_id}/messages")
async def create_conversation_message(
    conversation_id: uuid.UUID,
    message: ConversationMessageRequest,
    http_request: Request,
    chat: ConversationChat = Depends(get_conversation_chat),
    current_user: Actor = Depends(get_required_user),
    request_operation: OperationContext = Depends(get_required_operation),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
) -> StreamingResponse:
    if not isinstance(request_operation.origin, HttpOrigin):
        raise RuntimeError("conversation_http_origin_missing")
    operation = operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=request_operation.origin.request,
            conversation_id=conversation_id,
            turn_id=message.turn_id,
        ),
        credential=request_operation.credential,
    )
    attach_operation_context(
        http_request,
        operation,
        actor_id=str(current_user.id),
    )
    stream = await chat.stream(
        actor=current_user,
        operation=operation,
        conversation_id=conversation_id,
        request=message,
        client_ip=http_client_ip(http_request),
    )
    return StreamingResponse(stream, media_type="text/event-stream")
