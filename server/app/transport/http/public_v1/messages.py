import uuid

from app.bootstrap.execution import get_conversation_chat
from app.modules.conversations.application.chat import ConversationChat
from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
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
) -> StreamingResponse:
    stream = await chat.stream(
        actor=current_user,
        conversation_id=conversation_id,
        request=message,
        client_ip=(http_request.client.host if http_request.client else "unknown"),
    )
    return StreamingResponse(stream, media_type="text/event-stream")
