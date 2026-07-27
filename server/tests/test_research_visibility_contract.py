"""Contracts for private conversations and selectively shared Project outputs."""

from pathlib import Path
import uuid

import pytest
from app.api.highlight_api import CreateHighlightRequest
from app.database.models import (
    Annotation,
    Artifact,
    AudioOverview,
    DataTableExtractionJob,
    Highlight,
    PaperNote,
    Project,
)
from app.errors import AppError
from app.main import app
from app.policies.projects import ProjectAccess, ProjectPermissions
from app.policies.research import (
    can_manage_research_item,
    can_view_research_item,
    require_research_item_manager,
)
from pydantic import ValidationError

ROOT = Path(__file__).parents[2]


def _access(*, user_id: int, owner: bool) -> ProjectAccess:
    project = Project(id=uuid.uuid4(), owner_id=1, title="Research project")
    return ProjectAccess(
        project=project,
        user_id=user_id,
        is_owner=owner,
        collaborator=None,
        permissions=ProjectPermissions.all() if owner else ProjectPermissions(),
    )


def test_project_outputs_share_one_visibility_contract() -> None:
    project_scoped_models = (
        Artifact,
        AudioOverview,
        DataTableExtractionJob,
        Highlight,
        PaperNote,
    )
    for model in project_scoped_models:
        assert "is_shared" in model.__table__.c
        assert model.__table__.c.is_shared.nullable is False
        assert model.__table__.c.user_id.nullable is True

    # Annotation visibility deliberately follows its parent Highlight so the
    # two records can never contradict one another.
    assert "is_shared" not in Annotation.__table__.c


def test_shared_items_are_visible_but_hidden_items_remain_creator_only() -> None:
    creator = _access(user_id=2, owner=False)
    collaborator = _access(user_id=3, owner=False)
    owner = _access(user_id=1, owner=True)

    assert can_view_research_item(
        access=collaborator,
        created_by_id=creator.user_id,
        is_shared=True,
    )
    assert not can_view_research_item(
        access=collaborator,
        created_by_id=creator.user_id,
        is_shared=False,
    )
    assert can_view_research_item(
        access=creator,
        created_by_id=creator.user_id,
        is_shared=False,
    )
    assert can_manage_research_item(access=creator, created_by_id=creator.user_id)
    assert can_manage_research_item(access=owner, created_by_id=creator.user_id)
    assert not can_manage_research_item(
        access=collaborator,
        created_by_id=creator.user_id,
    )

    with pytest.raises(AppError) as exc_info:
        require_research_item_manager(
            access=collaborator,
            created_by_id=creator.user_id,
        )
    assert exc_info.value.code == "research_item_permission_denied"


def test_personal_highlights_cannot_claim_shared_visibility() -> None:
    with pytest.raises(ValidationError):
        CreateHighlightRequest.model_validate(
            {
                "paper_id": str(uuid.uuid4()),
                "raw_text": "Evidence",
                "shared": True,
            }
        )


def test_research_visibility_api_is_uniform_and_project_artifacts_hide_chat_ids() -> (
    None
):
    paths = app.openapi()["paths"]
    assert "/api/research/{kind}/{output_id}/visibility" in paths

    project_artifact_schema = paths["/api/projects/artifacts/{project_id}"]["get"]
    response_text = str(project_artifact_schema)
    assert "conversation_id" not in response_text
    assert "message_id" not in response_text


def test_clean_baseline_contains_visibility_constraints() -> None:
    baseline = next((ROOT / "server" / "migrations" / "versions").glob("*.py"))
    source = baseline.read_text(encoding="utf-8")
    for constraint in (
        "ck_artifacts_shared_project_scope",
        "ck_audio_overviews_shared_project",
        "ck_data_table_jobs_shared_project",
        "ck_highlights_shared_project",
        "ck_paper_notes_shared_project",
    ):
        assert constraint in source
