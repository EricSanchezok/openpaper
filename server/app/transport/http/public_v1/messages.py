import uuid

from app.bootstrap.container import build_conversation_chat
from app.database.database import get_db
from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

message_router = APIRouter()


@message_router.get("/capabilities")
def get_chat_capabilities(
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return build_conversation_chat(db=db).capabilities()


@message_router.post("/{conversation_id}/messages")
async def create_conversation_message(
    conversation_id: uuid.UUID,
    message: ConversationMessageRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> StreamingResponse:
    stream = await build_conversation_chat(db=db).stream(
        actor=current_user,
        conversation_id=conversation_id,
        request=message,
        client_ip=(http_request.client.host if http_request.client else "unknown"),
    )
    return StreamingResponse(stream, media_type="text/event-stream")
