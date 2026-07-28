"""Contracts for typed research outputs and creator-owned visibility."""

from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import uuid

import pytest
from app.database.models import (
    AnnotationComment,
    HighlightThread,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
    ResearchItemKind,
    ResearchScopeType,
)
from app.errors import AppError
from app.main import app
from app.policies.research import research_item_policy
from app.policies.research import research_item_visible_to
from app.repositories.research import research_repository
from app.schemas.research import CreateHighlightThreadRequest, ResearchVisibilityRequest
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).parents[2]


def _item(
    *,
    creator_id: int = 2,
    shared: bool = True,
    scope_type: ResearchScopeType = ResearchScopeType.PROJECT,
) -> ResearchItem:
    return ResearchItem(
        id=uuid.uuid4(),
        kind=ResearchItemKind.CITATION.value,
        created_by_id=creator_id,
        scope_type=scope_type.value,
        project_id=uuid.uuid4() if scope_type == ResearchScopeType.PROJECT else None,
        document_id=uuid.uuid4() if scope_type == ResearchScopeType.DOCUMENT else None,
        is_shared=shared,
    )


def test_research_items_use_one_metadata_contract_with_typed_payloads() -> None:
    assert {
        "kind",
        "created_by_id",
        "scope_type",
        "document_id",
        "project_id",
        "is_shared",
        "source_message_id",
    }.issubset(ResearchItem.__table__.c.keys())
    assert HighlightThread.__table__.c.research_item_id.primary_key
    assert ResearchAudioOverview.__table__.c.research_item_id.primary_key
    assert ResearchDataTable.__table__.c.research_item_id.primary_key
    assert "is_shared" not in AnnotationComment.__table__.c


def test_creator_is_only_manager_and_owner_has_no_override() -> None:
    db = MagicMock(spec=Session)
    item = _item(creator_id=2, shared=True)

    with patch(
        "app.policies.research.get_project_access",
        return_value=object(),
    ):
        creator = research_item_policy.evaluate(db, item=item, user_id=2)
        collaborator = research_item_policy.evaluate(db, item=item, user_id=3)
        owner = research_item_policy.evaluate(db, item=item, user_id=1)

    assert creator.can_view and creator.can_manage
    assert collaborator.can_view and not collaborator.can_manage
    assert owner.can_view and not owner.can_manage

    with (
        patch(
            "app.policies.research.get_project_access",
            return_value=object(),
        ),
        pytest.raises(AppError) as exc_info,
    ):
        research_item_policy.require_creator_manager(db, item=item, user_id=1)
    assert exc_info.value.code == "research_item_permission_denied"


def test_hidden_items_are_creator_only_and_creator_history_survives_access_loss() -> (
    None
):
    db = MagicMock(spec=Session)
    item = _item(creator_id=2, shared=False)

    with patch("app.policies.research.get_project_access", return_value=None):
        creator = research_item_policy.evaluate(db, item=item, user_id=2)
        collaborator = research_item_policy.evaluate(db, item=item, user_id=3)

    assert creator.can_view
    assert not creator.can_manage
    assert not creator.has_scope_access
    assert not collaborator.can_view


def test_research_item_id_visibility_is_enforced_in_the_sql_query() -> None:
    statement = str(
        research_item_visible_to(7).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "research_items.created_by_id = 7" in statement
    assert "library_papers.user_id = 7" in statement
    assert "project_collaborators.user_id = 7" in statement
    assert "research_items.is_shared IS true" in statement


def test_comment_capabilities_become_read_only_when_scope_access_is_lost() -> None:
    now = datetime.now(timezone.utc)
    comment = AnnotationComment(
        id=uuid.uuid4(),
        thread_id=uuid.uuid4(),
        created_by_id=2,
        content="Observation",
        role="user",
        created_at=now,
        updated_at=now,
    )

    response = research_repository.serialize_comment(
        comment,
        user_id=2,
        has_scope_access=False,
    )

    assert response.can_edit is False
    assert response.can_delete is False


def test_highlight_thread_with_other_authors_requires_explicit_delete_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _item(
        creator_id=2,
        shared=True,
        scope_type=ResearchScopeType.DOCUMENT,
    )
    item.kind = ResearchItemKind.HIGHLIGHT_THREAD.value
    db = MagicMock(spec=Session)
    db.scalar.return_value = 3
    monkeypatch.setattr(
        research_repository,
        "require_creator_owned",
        lambda *_args, **_kwargs: item,
    )

    with pytest.raises(AppError) as exc_info:
        research_repository.delete_item(
            db,
            item_id=item.id,
            user_id=2,
            confirm_delete_replies=False,
        )

    assert exc_info.value.code == "highlight_thread_has_other_replies"
    assert exc_info.value.details == {"affected_reply_count": 3}
    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_personal_research_is_always_private() -> None:
    db = MagicMock(spec=Session)
    item = _item(
        creator_id=2,
        shared=False,
        scope_type=ResearchScopeType.PERSONAL,
    )

    creator = research_item_policy.evaluate(db, item=item, user_id=2)
    stranger = research_item_policy.evaluate(db, item=item, user_id=3)

    assert creator.can_view and creator.can_manage
    assert not stranger.can_view and not stranger.can_manage


def test_highlight_request_is_strict_and_shared_by_default() -> None:
    request = CreateHighlightThreadRequest.model_validate({"quote_text": "Evidence"})
    assert request.shared is True

    with pytest.raises(ValidationError):
        CreateHighlightThreadRequest.model_validate(
            {"quote_text": "Evidence", "project_id": str(uuid.uuid4())}
        )
    with pytest.raises(ValidationError):
        ResearchVisibilityRequest.model_validate(
            {"shared": True, "creator_override": True}
        )


def test_research_api_exposes_only_the_new_typed_routes() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/documents/{document_id}/research-items",
        "/api/documents/{document_id}/highlight-threads",
        "/api/highlight-threads/{thread_id}",
        "/api/highlight-threads/{thread_id}/comments",
        "/api/annotation-comments/{comment_id}",
        "/api/projects/{project_id}/research-items",
        "/api/research-items/{item_id}",
    }
    assert expected.issubset(paths)
    assert not any("/api/highlight/" in path for path in paths)
    assert not any("/api/annotation/" in path for path in paths)
    assert not any("/api/projects/artifacts" in path for path in paths)
    assert not any("/visibility" in path for path in paths)


def test_public_paper_share_has_no_research_route() -> None:
    paths = app.openapi()["paths"]
    public_paths = [path for path in paths if "/public/" in path or "/share/" in path]
    assert all("research" not in path for path in public_paths)


def test_clean_baseline_contains_typed_research_constraints() -> None:
    baseline = next((ROOT / "server" / "migrations" / "versions").glob("*.py"))
    source = baseline.read_text(encoding="utf-8")
    for table_or_constraint in (
        "research_items",
        "highlight_threads",
        "annotation_comments",
        "citation_outputs",
        "research_audio_overviews",
        "research_data_tables",
        "ck_research_items_scope_consistency",
        "ck_research_items_personal_private",
    ):
        assert table_or_constraint in source
    assert 'op.create_table("artifacts"' not in source
