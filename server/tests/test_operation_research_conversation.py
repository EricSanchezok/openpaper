"""Focused provenance tests for Research and Conversation mutations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.bootstrap.adapters.research_repository import research_repository
from app.database.models import AnnotationComment, Conversation
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationMoveRequest,
    ConversationToolPermissionsRequest,
    ConversationUpdateRequest,
    LibraryPaperContext,
)
from app.modules.conversations.application.conversations import (
    ConversationChange,
    Conversations,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.research.application.contracts import (
    CreateHighlightThreadRequest,
    UpdateAnnotationCommentRequest,
)
from app.modules.research.application.items import ResearchItemChange, ResearchItems
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain.enums import ConversationScopeType, RoleType
from app.shared.domain.workspace_permissions import WorkspacePermission
from sqlalchemy.orm import Session


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(request_id=uuid4())),
        credential=CredentialRef(kind=CredentialKind.CLOUD_SESSION),
    )


def test_research_creation_requires_explicit_role_and_journals_change() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    response = SimpleNamespace(id=uuid4())
    gateway.create_highlight.return_value = response
    service = ResearchItems(gateway, journal=journal)
    actor = _actor()
    operation = _operation()
    request = CreateHighlightThreadRequest(quote_text="Evidence")

    assert (
        service.create_highlight(
            actor=actor,
            operation=operation,
            document_id=uuid4(),
            request=request,
            content_role=RoleType.ASSISTANT,
        )
        is response
    )

    assert (
        gateway.create_highlight.call_args.kwargs["content_role"] is RoleType.ASSISTANT
    )
    assert journal.append.call_args.kwargs["action"] == "research.highlight_created"

    with pytest.raises(TypeError):
        service.create_highlight(
            actor=actor,
            operation=operation,
            document_id=uuid4(),
            request=request,
            content_role="assistant",  # type: ignore[arg-type]
        )


def test_research_noop_update_does_not_append_journal() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    response = SimpleNamespace(id=uuid4())
    gateway.update_comment.return_value = ResearchItemChange(
        value=response,
        changed=False,
    )
    service = ResearchItems(gateway, journal=journal)

    assert (
        service.update_comment(
            actor=_actor(),
            operation=_operation(),
            comment_id=response.id,
            request=UpdateAnnotationCommentRequest(content="unchanged"),
        )
        is response
    )
    journal.append.assert_not_called()


def test_research_repository_reports_identical_comment_as_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    comment = AnnotationComment(
        id=uuid4(),
        thread_id=uuid4(),
        created_by_id=7,
        content="unchanged",
        role=RoleType.USER.value,
    )
    db = MagicMock(spec=Session)
    monkeypatch.setattr(
        research_repository,
        "require_owned_comment",
        lambda *_args, **_kwargs: comment,
    )

    result = research_repository.update_comment(
        db,
        comment_id=comment.id,
        user_id=7,
        content="unchanged",
    )

    assert result.changed is False
    assert result.value is comment
    db.flush.assert_not_called()


def _conversations(
    *,
    gateway: MagicMock,
    journal: MagicMock,
) -> Conversations:
    return Conversations(
        gateway=gateway,
        message_cursors=MagicMock(),
        journal=journal,
    )


def test_conversation_noop_does_not_append_journal() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    response = SimpleNamespace(id=uuid4())
    gateway.update.return_value = ConversationChange(
        value=response,
        changed=False,
    )
    service = _conversations(gateway=gateway, journal=journal)

    result = service.update(
        actor=_actor(),
        operation=_operation(),
        conversation_id=response.id,
        request=ConversationUpdateRequest(title="unchanged"),
    )

    assert result is response
    journal.append.assert_not_called()


def test_conversation_repository_identical_update_is_noop() -> None:
    conversation = Conversation(
        id=uuid4(),
        title="unchanged",
        user_id=7,
        scope_type="global",
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation

    result = conversation_repository.update(
        db,
        conversation_id=conversation.id,
        user_id=7,
        request=ConversationUpdateRequest(title="unchanged"),
    )

    assert result.changed is False
    assert result.value is conversation
    db.flush.assert_not_called()


def test_conversation_repository_same_scope_and_context_are_noops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=uuid4(),
        title="Library",
        user_id=7,
        scope_type=ConversationScopeType.GLOBAL.value,
        paper_context_kind="library",
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation
    db.scalars.return_value.all.return_value = []
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository."
        "conversation_policy.require_can_continue",
        lambda *_args, **_kwargs: None,
    )

    move_result = conversation_repository.move(
        db,
        conversation_id=conversation.id,
        user_id=7,
        request=ConversationMoveRequest(scope_type="global"),
    )
    context_result = conversation_repository.update_paper_context(
        db,
        conversation_id=conversation.id,
        user_id=7,
        request=LibraryPaperContext(),
    )

    assert move_result.changed is False
    assert context_result.changed is False
    db.execute.assert_not_called()
    db.flush.assert_not_called()


def test_conversation_repository_same_tool_permissions_are_noop() -> None:
    conversation = Conversation(
        id=uuid4(),
        title="Library",
        user_id=7,
        scope_type=ConversationScopeType.GLOBAL.value,
        tool_permissions=["read", "write"],
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation

    result = conversation_repository.update_tool_permissions(
        db,
        conversation_id=conversation.id,
        user_id=7,
        request=ConversationToolPermissionsRequest(
            permissions=[WorkspacePermission.READ, WorkspacePermission.WRITE],
        ),
    )

    assert result.changed is False
    db.flush.assert_not_called()


def test_auto_title_only_journals_an_applied_title() -> None:
    gateway = MagicMock()
    gateway.update_title.return_value = False
    journal = MagicMock(spec=OperationJournal)
    service = _conversations(gateway=gateway, journal=journal)
    conversation_id = uuid4()

    response = service.apply_generated_title(
        actor=_actor(),
        operation=_operation(),
        conversation_id=conversation_id,
        title="Same title",
    )

    assert response.title == "Same title"
    journal.append.assert_not_called()


def test_created_resource_ref_uses_canonical_uuid() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    conversation_id = UUID("00000000-0000-0000-0000-000000000007")
    gateway.create.return_value = SimpleNamespace(id=conversation_id)
    service = _conversations(gateway=gateway, journal=journal)

    service.create(
        actor=_actor(),
        operation=_operation(),
        request=ConversationCreateRequest(
            scope_type=ConversationScopeType.GLOBAL,
        ),
    )

    resource = journal.append.call_args.kwargs["resources"][0]
    assert resource.type == "conversation"
    assert resource.id == str(conversation_id)
