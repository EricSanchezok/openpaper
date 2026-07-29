import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from app.api.conversation_api import get_conversation, get_conversation_messages
from app.api.message_api import chat_message_multipaper
from app.repositories.messages import message_repository
from app.database.models import Conversation, Message
from app.errors import AppError
from app.main import app
from app.repositories.conversations import conversation_repository
from app.schemas.conversations import (
    ConversationCreateRequest,
    ConversationMoveRequest,
    ConversationUpdateRequest,
    serialize_messages,
)
from app.schemas.message import MultiPaperChatRequest
from app.repositories.messages import MessageCreate
from app.shared.application import Actor
from sqlalchemy.orm import Session
from pydantic import ValidationError
from starlette.requests import Request


def _current_user() -> Actor:
    return Actor(
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

    assert serialized[0].trace == {
        "citations": [],
        "tool_calls": [{"name": "search", "status": "completed"}],
        "status_messages": ["Searching the library"],
    }


def test_conversation_scope_contract_is_private_and_unified() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}/scope" in paths
    assert "/api/v1/conversations/{conversation_id}/messages" in paths
    assert not any(path.startswith("/api/v1/conversation/") for path in paths)
    assert not any(path.startswith("/api/v1/projects/conversations") for path in paths)
    assert not any("conversation/share" in path for path in paths)

    table = Conversation.__table__
    assert table.c.user_id.nullable is False
    assert table.c.title.nullable is False
    assert {
        "scope_type",
        "project_id",
        "document_id",
        "context_deleted_at",
        "pinned_at",
        "archived_at",
        "scope_label_snapshot",
    } <= set(table.c.keys())
    assert "conversable_id" not in table.c
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
        scope_type="global",
    )
    original_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    conversation.updated_at = original_updated_at
    db.scalar.side_effect = [conversation, 3]

    message = message_repository.create(
        db,
        request=MessageCreate(
            conversation_id=conversation.id,
            role="user",
            content="Question",
        ),
        user_id=_current_user().id,
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
        message_repository.create(
            db,
            request=MessageCreate(
                conversation_id=uuid.uuid4(),
                role="user",
                content="Question",
            ),
            user_id=_current_user().id,
        )

    assert exc_info.value.code == "conversation_not_found"


def test_owned_conversation_lookup_filters_id_and_user_in_one_query() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = None

    with pytest.raises(AppError):
        conversation_repository.require_owned(
            db,
            conversation_id=uuid.uuid4(),
            user_id=73,
        )

    statement = str(db.scalar.call_args.args[0])
    assert "conversations.id" in statement
    assert "conversations.user_id" in statement


def test_paper_conversation_scope_is_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Paper",
        user_id=1,
        scope_type="paper",
        document_id=uuid.uuid4(),
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation
    monkeypatch.setattr(
        "app.repositories.conversations.conversation_policy.require_can_continue",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(AppError) as exc_info:
        conversation_repository.move(
            db,
            conversation_id=conversation.id,
            user_id=1,
            request=ConversationMoveRequest(scope_type="global"),
        )

    assert exc_info.value.code == "paper_conversation_scope_fixed"
    db.commit.assert_not_called()


def test_archiving_a_conversation_also_unpins_it() -> None:
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Pinned",
        user_id=1,
        scope_type="global",
        pinned_at=now,
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation

    updated = conversation_repository.update(
        db,
        conversation_id=conversation.id,
        user_id=1,
        request=ConversationUpdateRequest(archived=True),
    )

    assert updated.archived_at is not None
    assert updated.pinned_at is None
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_chat_scope_is_rejected_before_rate_or_concurrency_leases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Paper",
        user_id=1,
        scope_type="paper",
        document_id=uuid.uuid4(),
    )
    monkeypatch.setattr(
        "app.api.message_api.has_token_credits",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: conversation,
    )
    monkeypatch.setattr(
        "app.api.message_api.conversation_policy.require_can_continue",
        lambda *_args, **_kwargs: None,
    )
    enforce_rate_limit = MagicMock()
    acquire_concurrency = MagicMock()
    monkeypatch.setattr(
        "app.api.message_api.enforce_rate_limit",
        enforce_rate_limit,
    )
    monkeypatch.setattr(
        "app.api.message_api.acquire_concurrency",
        acquire_concurrency,
    )
    http_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/message/chat/everything",
            "headers": [],
            "client": ("127.0.0.1", 1234),
        }
    )

    with pytest.raises(AppError) as exc_info:
        await chat_message_multipaper(
            request=MultiPaperChatRequest(
                conversation_id=str(conversation.id),
                user_query="Question",
            ),
            http_request=http_request,
            db=MagicMock(spec=Session),
            current_user=_current_user(),
        )

    assert exc_info.value.code == "conversation_scope_mismatch"
    enforce_rate_limit.assert_not_called()
    acquire_concurrency.assert_not_called()


def test_conversation_scope_payloads_reject_inconsistent_ids() -> None:
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate({"scope_type": "project"})
    with pytest.raises(ValidationError):
        ConversationCreateRequest.model_validate(
            {
                "scope_type": "global",
                "scope_id": str(uuid.uuid4()),
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
        scope_type="global",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: conversation,
    )
    monkeypatch.setattr(
        message_repository,
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
        get_conversation_messages(
            conversation_id=conversation_id,
            page=1,
            page_size=10,
            db=MagicMock(spec=Session),
            current_user=_current_user(),
        )
