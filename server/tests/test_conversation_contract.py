import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from app.api.conversation_api import get_conversation
from app.database.crud.message_crud import message_crud
from app.database.models import Conversation, Message
from app.errors import AppError
from app.main import app
from app.repositories.conversations import conversation_repository
from app.schemas.conversations import ConversationCreateRequest
from app.database.crud.message_crud import MessageCreate
from app.schemas.orm_responses import serialize_messages
from app.schemas.user import CurrentUser
from sqlalchemy.orm import Session
from pydantic import ValidationError


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


def test_conversation_scope_contract_is_private_and_unified() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/conversations" in paths
    assert "/api/conversations/{conversation_id}/move" in paths
    assert "/api/conversations/{conversation_id}/detach" in paths
    assert not any(path.startswith("/api/conversation/") for path in paths)
    assert not any(path.startswith("/api/projects/conversations") for path in paths)
    assert not any("conversation/share" in path for path in paths)

    table = Conversation.__table__
    assert table.c.user_id.nullable is False
    assert table.c.title.nullable is False
    assert {"pinned_at", "archived_at", "scope_label_snapshot"} <= set(table.c.keys())
    assert "user_id" not in Message.__table__.c
    assert any(
        constraint.name == "uq_messages_conversation_sequence"
        for constraint in Message.__table__.constraints
    )


def test_message_creation_locks_and_touches_the_owned_conversation() -> None:
    db = MagicMock(spec=Session)
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Conversation",
        user_id=1,
        conversable_type="everything",
    )
    original_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    conversation.updated_at = original_updated_at
    db.scalar.side_effect = [conversation, 3]

    message = message_crud.create(
        db,
        obj_in=MessageCreate(
            conversation_id=conversation.id,
            role="user",
            content="Question",
        ),
        user=_current_user(),
        auto_commit=False,
    )

    assert message is not None
    assert message.sequence == 4
    assert conversation.updated_at > original_updated_at
    ownership_statement = db.scalar.call_args_list[0].args[0]
    assert "FOR UPDATE" in str(ownership_statement)


def test_message_creation_rejects_a_conversation_owned_by_someone_else() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = None

    with pytest.raises(AppError) as exc_info:
        message_crud.create(
            db,
            obj_in=MessageCreate(
                conversation_id=uuid.uuid4(),
                role="user",
                content="Question",
            ),
            user=_current_user(),
        )

    assert exc_info.value.code == "conversation_not_found"


def test_conversation_scope_payloads_reject_inconsistent_ids() -> None:
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate({"conversable_type": "project"})
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate(
            {
                "conversable_type": "everything",
                "conversable_id": str(uuid.uuid4()),
            }
        )


def test_missing_conversation_is_the_only_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AppError(
                code="conversation_not_found",
                message="Conversation not found",
                status_code=404,
            )
        ),
    )

    with pytest.raises(AppError) as exc_info:
        get_conversation(
            conversation_id=uuid.uuid4(),
            page=1,
            page_size=10,
            db=MagicMock(spec=Session),
            current_user=_current_user(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "conversation_not_found"


def test_conversation_serialization_errors_are_not_reported_as_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = uuid.uuid4()
    conversation = Conversation(
        id=conversation_id,
        title="Conversation",
        user_id=1,
        conversable_type="everything",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: conversation,
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
        get_conversation(
            conversation_id=conversation_id,
            page=1,
            page_size=10,
            db=MagicMock(spec=Session),
            current_user=_current_user(),
        )
