import asyncio
import uuid
from unittest.mock import MagicMock

import pytest
from app.api.conversation_api import get_conversation
from app.database.crud.conversation_crud import conversation_crud
from app.database.crud.message_crud import message_crud
from app.database.models import Message
from app.schemas.orm_responses import serialize_messages
from app.schemas.user import CurrentUser
from fastapi import HTTPException
from sqlalchemy.orm import Session


def _current_user() -> CurrentUser:
    return CurrentUser(
        id=1,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def test_assistant_trace_serializes_as_an_object() -> None:
    message = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        user_id=1,
        role="assistant",
        content="Answer",
        references={"citations": []},
        trace={
            "citations": [],
            "tool_calls": [{"name": "search", "status": "completed"}],
            "status_messages": ["Searching the library"],
        },
        sequence=2,
    )
    message.artifacts = []

    serialized = serialize_messages([message])

    assert serialized[0]["trace"] == {
        "citations": [],
        "tool_calls": [{"name": "search", "status": "completed"}],
        "status_messages": ["Searching the library"],
    }


def test_missing_conversation_is_the_only_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversation_crud,
        "get",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            get_conversation(
                conversation_id=uuid.uuid4(),
                db=MagicMock(spec=Session),
                current_user=_current_user(),
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "conversation_not_found"


def test_conversation_serialization_errors_are_not_reported_as_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid.uuid4()
    monkeypatch.setattr(
        conversation_crud,
        "get",
        lambda *_args, **_kwargs: MagicMock(
            id=conversation_id,
            title="Conversation",
        ),
    )
    monkeypatch.setattr(
        message_crud,
        "get_conversation_messages",
        lambda *_args, **_kwargs: [MagicMock()],
    )

    with pytest.raises(ValueError, match="invalid message payload"):
        monkeypatch.setattr(
            "app.api.conversation_api.serialize_messages",
            lambda _messages: (_ for _ in ()).throw(
                ValueError("invalid message payload")
            ),
        )
        asyncio.run(
            get_conversation(
                conversation_id=conversation_id,
                db=MagicMock(spec=Session),
                current_user=_current_user(),
            )
        )
