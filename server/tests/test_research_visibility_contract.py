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
from app.transport.http.public_v1.projects.responses import _project_counts
from app.modules.research.infrastructure.access import research_item_policy
from app.modules.research.infrastructure.access import research_item_visible_to
from app.modules.research.infrastructure.repository import research_repository
from app.modules.research.application.contracts import (
    CitationSnapshot,
    CreateHighlightThreadRequest,
    ResearchVisibilityRequest,
)
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
        "app.modules.research.infrastructure.access.get_project_access",
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
            "app.modules.research.infrastructure.access.get_project_access",
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

    with patch(
        "app.modules.research.infrastructure.access.get_project_access",
        return_value=None,
    ):
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


def test_citation_snapshot_is_strictly_validated_before_persistence() -> None:
    snapshot = CitationSnapshot.model_validate(
        {
            "kind": "citation",
            "document_id": str(uuid.uuid4()),
            "preferred_style": "APA",
            "style_display": "APA 7th Edition",
            "data": {
                "document_id": str(uuid.uuid4()),
                "title": "Typed citation",
                "authors": ["Researcher"],
            },
            "method": "deterministic",
            "missing_fields": [],
            "confidence": 0.95,
        }
    )
    assert snapshot.kind == "citation"

    with pytest.raises(ValidationError):
        CitationSnapshot.model_validate(
            {
                **snapshot.model_dump(mode="json"),
                "private_trace": {"query": "must not persist"},
            }
        )


def test_research_api_exposes_only_the_new_typed_routes() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/papers/{document_id}/research-items",
        "/api/v1/papers/{document_id}/highlight-threads",
        "/api/v1/highlight-threads/{thread_id}",
        "/api/v1/highlight-threads/{thread_id}/comments",
        "/api/v1/annotation-comments/{comment_id}",
        "/api/v1/projects/{project_id}/research-items",
        "/api/v1/research-items/{item_id}",
    }
    assert expected.issubset(paths)
    assert not any("/api/v1/highlight/" in path for path in paths)
    assert not any("/api/v1/annotation/" in path for path in paths)
    assert not any("/api/v1/projects/artifacts" in path for path in paths)
    assert not any("/visibility" in path for path in paths)


def test_public_paper_share_has_no_research_route() -> None:
    paths = app.openapi()["paths"]
    public_paths = [path for path in paths if "/public/" in path or "/share/" in path]
    assert all("research" not in path for path in public_paths)


def test_project_summary_counts_only_research_visible_to_the_requester() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = 0

    _project_counts(
        db,
        project_id=uuid.uuid4(),
        current_user_id=73,
    )

    audio_statement = str(db.scalar.call_args_list[2].args[0])
    table_statement = str(db.scalar.call_args_list[3].args[0])
    for statement in (audio_statement, table_statement):
        assert "research_items.is_shared IS true" in statement
        assert "research_items.created_by_id" in statement


def test_clean_baseline_contains_typed_research_constraints() -> None:
    baseline = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))[0]
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
