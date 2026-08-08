import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from app.database.models import (
    Conversation,
    ConversationContextDocument,
    ConversationContextProject,
    ConversationResponse,
    ConversationTurn,
)
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.main import app
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.bootstrap.adapters.conversation_lifecycle import (
    SqlAlchemyConversationGateway,
)
from app.bootstrap.adapters.conversation_chat_data import (
    SqlAlchemyConversationChatData,
)
from app.modules.conversations.application.chat import ConversationChatScope
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    LibraryPaperContext,
    ConversationMoveRequest,
    SelectedPaperContext,
    ConversationUpdateRequest,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationAssistantItem,
    ConversationTrace,
)
from app.modules.conversations.infrastructure.presenters import serialize_turns
from app.modules.conversations.infrastructure.turn_repository import turn_repository
from app.shared.application import Actor
from app.shared.domain.enums import ConversationScopeType
from sqlalchemy.orm import Session
from pydantic import ValidationError


def _current_user() -> Actor:
    return Actor(
        id=1,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def test_response_trace_serializes_as_a_typed_product_trace() -> None:
    turn = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        created_operation_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        user_query="Question",
        reasoning_level="standard",
        locale="en",
        time_zone="UTC",
        sequence=1,
    )
    response = ConversationResponse(
        id=uuid.uuid4(),
        turn_id=turn.id,
        created_operation_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        variant_index=1,
        status="completed",
        content="Answer",
        references={"annotations": [], "sources": []},
        trace={
            "entries": [
                {
                    "kind": "activity",
                    "id": "search-1",
                    "sequence": 1,
                    "category": "search",
                    "state": "succeeded",
                    "subject": "reasoning compression",
                    "source_count": 2,
                }
            ],
            "citation_summary": {
                "source_count": 2,
                "annotation_count": 1,
                "rejected_source_count": 0,
            },
        },
        suggestions_status="idle",
    )
    response.research_items = []
    turn.responses = [response]
    turn.selected_response_id = response.id

    serialized = serialize_turns([turn], latest_turn_id=turn.id)

    assert serialized[0].responses[0].trace == ConversationTrace.model_validate(
        response.trace
    )
    assert serialized[0].selected_response_id == response.id


def test_completed_assistant_items_require_visible_content() -> None:
    with pytest.raises(ValidationError):
        ConversationAssistantItem(
            id="assistant:item",
            sequence=1,
            phase="final",
            content="",
        )


def test_conversation_scope_contract_is_private_and_unified() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/v1/conversations" in paths
    assert "/api/v1/conversations/{conversation_id}/scope" in paths
    assert "/api/v1/conversations/{conversation_id}/context" in paths
    assert "/api/v1/conversations/{conversation_id}/turns" in paths
    assert "/api/v1/conversations/{conversation_id}/turns/{turn_id}/responses" in paths
    assert (
        "/api/v1/conversations/{conversation_id}/turns/{turn_id}/selected-response"
        in paths
    )
    assert (
        "/api/v1/conversations/{conversation_id}/responses/{response_id}/suggestions"
        in paths
    )
    assert "/api/v1/conversations/{conversation_id}/messages" not in paths
    assert not any(path.startswith("/api/v1/conversation/") for path in paths)
    assert not any(path.startswith("/api/v1/projects/conversations") for path in paths)
    assert not any("conversation/share" in path for path in paths)

    table = Conversation.__table__
    assert table.c.user_id.nullable is False
    assert table.c.title.nullable is False
    assert {
        "scope_type",
        "paper_context_kind",
        "project_id",
        "document_id",
        "context_deleted_at",
        "pinned_at",
        "archived_at",
        "scope_label_snapshot",
    } <= set(table.c.keys())
    assert "conversable_id" not in table.c
    assert {
        "conversation_id",
        "project_id",
    } <= set(ConversationContextProject.__table__.c.keys())
    assert {
        "conversation_id",
        "document_id",
    } <= set(ConversationContextDocument.__table__.c.keys())
    assert "user_id" not in ConversationTurn.__table__.c
    assert any(
        constraint.name == "uq_conversation_turns_conversation_sequence"
        for constraint in ConversationTurn.__table__.constraints
    )
    assert any(
        constraint.name == "uq_conversation_responses_turn_variant"
        for constraint in ConversationResponse.__table__.constraints
    )


def test_conversation_turns_expose_a_typed_standard_sse_contract() -> None:
    response = app.openapi()["paths"]["/api/v1/conversations/{conversation_id}/turns"][
        "post"
    ]["responses"]["200"]

    assert response["content"]["text/event-stream"]["schema"]["$ref"] == (
        "#/components/schemas/ConversationStreamEventSchema"
    )
    event_schema = app.openapi()["components"]["schemas"][
        "ConversationStreamEventSchema"
    ]["oneOf"]
    assert {item["$ref"].rsplit("/", maxsplit=1)[-1] for item in event_schema} == {
        "ConversationStreamStartEvent",
        "ConversationStreamActivityEvent",
        "ConversationStreamAssistantItemStartEvent",
        "ConversationStreamAssistantItemDeltaEvent",
        "ConversationStreamAssistantItemCompleteEvent",
        "ConversationStreamReferencesEvent",
        "ConversationStreamCompleteEvent",
        "ConversationStreamErrorEvent",
    }


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
        "app.bootstrap.adapters.conversation_repository.conversation_policy.require_can_continue",
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


def test_moving_project_conversation_to_library_resets_paper_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Project",
        user_id=1,
        scope_type="project",
        project_id=uuid.uuid4(),
        paper_context_kind="selection",
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository.conversation_policy.require_can_continue",
        lambda *_args, **_kwargs: None,
    )

    move_result = conversation_repository.move(
        db,
        conversation_id=conversation.id,
        user_id=1,
        request=ConversationMoveRequest(scope_type="global"),
    )
    moved = move_result.value

    assert move_result.changed is True
    assert moved.scope_type == "global"
    assert moved.project_id is None
    assert moved.paper_context_kind == "library"
    assert db.execute.call_count == 2
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

    update_result = conversation_repository.update(
        db,
        conversation_id=conversation.id,
        user_id=1,
        request=ConversationUpdateRequest(archived=True),
    )
    updated = update_result.value

    assert update_result.changed is True
    assert updated.archived_at is not None
    assert updated.pinned_at is None
    db.commit.assert_not_called()
    db.flush.assert_called()


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


def test_selected_paper_context_deduplicates_and_sorts_ids() -> None:
    first = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second = uuid.UUID("00000000-0000-0000-0000-000000000002")

    context = SelectedPaperContext.model_validate(
        {
            "project_ids": [str(second), str(first), str(second)],
            "document_ids": [str(second), str(first), str(first)],
        }
    )

    assert context.project_ids == [first, second]
    assert context.document_ids == [first, second]


def test_library_paper_context_rejects_selection_fields() -> None:
    with pytest.raises(ValidationError):
        LibraryPaperContext.model_validate(
            {"kind": "library", "document_ids": [str(uuid.uuid4())]}
        )


def test_conversation_context_keeps_anchor_and_drops_lost_extra_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_project = uuid.uuid4()
    lost_project = uuid.uuid4()
    accessible_document = uuid.uuid4()
    lost_document = uuid.uuid4()
    conversation = Conversation(
        id=uuid.uuid4(),
        title="Project chat",
        user_id=1,
        scope_type="project",
        project_id=anchor_project,
        paper_context_kind="selection",
    )
    db = MagicMock(spec=Session)
    project_rows = MagicMock()
    project_rows.all.return_value = [lost_project]
    document_rows = MagicMock()
    document_rows.all.return_value = [accessible_document, lost_document]
    db.scalars.side_effect = [project_rows, document_rows]
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository.get_project_access",
        lambda _db, *, project_id, user_id: (
            object() if project_id == anchor_project else None
        ),
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository.get_document_access",
        lambda _db, *, document_id, user_id: (
            object() if document_id == accessible_document else None
        ),
    )

    context = conversation_repository.paper_context(
        db,
        conversation=conversation,
        user_id=1,
    )

    assert context.kind == "selection"
    assert context.project_ids == [anchor_project]
    assert context.document_ids == [accessible_document]


def test_global_conversation_defaults_to_accessible_library_context() -> None:
    db = MagicMock(spec=Session)

    conversation = conversation_repository.create(
        db,
        request=ConversationCreateRequest(scope_type="global"),
        user_id=1,
        refresh_result=False,
    )

    assert conversation.paper_context_kind == "library"
    db.commit.assert_not_called()
    db.flush.assert_called()


def test_paper_context_snapshot_only_loads_anchor_full_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_id = uuid.uuid4()
    extra_id = uuid.uuid4()
    papers = {
        anchor_id: MagicMock(
            id=anchor_id,
            title="Anchor",
            abstract="Anchor abstract",
            raw_content="Anchor full text",
            keywords=["anchor"],
            authors=["A"],
            publish_date=None,
        ),
        extra_id: MagicMock(
            id=extra_id,
            title="Extra",
            abstract="Must not be injected",
            raw_content="Must not be injected",
            keywords=["extra"],
            authors=["B"],
            publish_date=None,
        ),
    }
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_chat_data.document_repository.find_accessible",
        lambda _db, *, document_id, user: papers.get(document_id),
    )
    db = MagicMock(spec=Session)
    db.execute.return_value.all.return_value = []
    adapter = SqlAlchemyConversationChatData(db)

    snapshot = adapter.context(
        actor=_current_user(),
        scope=ConversationChatScope(
            scope_type=ConversationScopeType.PAPER,
            project_id=None,
            document_id=anchor_id,
            paper_context=SelectedPaperContext(
                document_ids=[anchor_id, extra_id],
            ),
            tool_permissions=frozenset(WorkspacePermission),
            title_is_default=False,
        ),
    )

    by_id = {paper.document_id: paper for paper in snapshot.papers}
    assert by_id[anchor_id].raw_content == "Anchor full text"
    assert by_id[anchor_id].abstract == "Anchor abstract"
    assert by_id[extra_id].raw_content is None
    assert by_id[extra_id].abstract is None


def test_missing_conversation_is_the_only_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        conversation_repository,
        "require_owned",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AppError(
                code="conversation_not_found",
                message="Conversation not found",
                kind=FailureKind.NOT_FOUND,
            )
        ),
    )

    with pytest.raises(AppError) as exc_info:
        SqlAlchemyConversationGateway(MagicMock(spec=Session)).get(
            conversation_id=uuid.uuid4(),
            user_id=_current_user().id,
        )

    assert exc_info.value.kind is FailureKind.NOT_FOUND
    assert exc_info.value.code == "conversation_not_found"


def test_conversation_turn_serialization_errors_are_not_reported_as_404(
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
    gateway = SqlAlchemyConversationGateway(MagicMock(spec=Session))

    with pytest.raises(ValueError, match="invalid message payload"):
        monkeypatch.setattr(
            "app.bootstrap.adapters.conversation_lifecycle.serialize_turns",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("invalid message payload")
            ),
        )
        monkeypatch.setattr(
            turn_repository,
            "list_turns",
            lambda *_args, **_kwargs: [MagicMock()],
        )
        monkeypatch.setattr(
            turn_repository,
            "latest_turn_id",
            lambda *_args, **_kwargs: None,
        )
        gateway.turns(
            conversation_id=conversation_id,
            offset=0,
            limit=10,
            user_id=_current_user().id,
        )
