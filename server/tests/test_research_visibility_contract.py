"""Contracts for private conversations and selectively shared Project outputs."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import uuid

import pytest
from app.api.highlight_api import CreateHighlightRequest
from app.database.crud.annotation_crud import annotation_crud
from app.database.crud.artifact_crud import artifact_crud
from app.database.crud.audio_overview_crud import audio_overview_crud
from app.database.crud.highlight_crud import highlight_crud
from app.database.crud.projects.project_data_table_crud import data_table_job_crud
from app.database.models import (
    Annotation,
    Artifact,
    AuthUser,
    AudioOverview,
    ConversableType,
    DataTableExtractionJob,
    Highlight,
    JobStatus,
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
from app.schemas.user import CurrentUser
from app.schemas.orm_responses import serialize_data_table_job
from pydantic import ValidationError
from sqlalchemy.orm import Session

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
    assert can_view_research_item(
        access=owner,
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


def test_owner_lists_include_hidden_project_outputs() -> None:
    owner = _access(user_id=1, owner=True)
    user = CurrentUser(
        id=1,
        email="owner@example.com",
        display_name="Owner",
        status="active",
        email_verified=True,
    )
    db = MagicMock(spec=Session)
    db.scalars.return_value.all.return_value = []
    db.scalars.return_value.unique.return_value.all.return_value = []

    with patch(
        "app.database.crud.artifact_crud.require_project_research_access",
        return_value=owner,
    ):
        artifact_crud.list_for_project(
            db,
            project_id=owner.project.id,
            user=user,
        )
    assert "artifacts.is_shared IS true" not in str(db.scalars.call_args.args[0])

    with patch(
        "app.database.crud.audio_overview_crud.get_project_access",
        return_value=owner,
    ):
        audio_overview_crud.get_by_conversable_and_user(
            db,
            conversable_id=owner.project.id,
            conversable_type=ConversableType.PROJECT,
            current_user=user,
        )
    assert "audio_overviews.is_shared IS true" not in str(db.scalars.call_args.args[0])

    with patch(
        "app.database.crud.projects.project_data_table_crud.get_project_access",
        return_value=owner,
    ):
        data_table_job_crud.get_by_project(
            db,
            project_id=owner.project.id,
            user=user,
        )
    assert "data_table_extraction_jobs.is_shared IS true" not in str(
        db.scalars.call_args.args[0]
    )

    with (
        patch("app.database.crud.highlight_crud.require_document_access"),
        patch(
            "app.database.crud.highlight_crud.require_project_research_access",
            return_value=owner,
        ),
    ):
        highlight_crud.get_highlights_by_paper_id(
            db,
            paper_id=uuid.uuid4(),
            project_id=owner.project.id,
            user=user,
        )
    assert "highlights.is_shared IS true" not in str(db.scalars.call_args.args[0])


def test_data_table_response_includes_visibility_and_creator_attribution() -> None:
    now = datetime.now(timezone.utc)
    creator = AuthUser(
        id=2,
        email="collaborator@example.com",
        password_hash="not-used",
        display_name="Research Collaborator",
        status="active",
    )
    job = DataTableExtractionJob(
        id=uuid.uuid4(),
        user_id=creator.id,
        project_id=uuid.uuid4(),
        columns=["Outcome"],
        task_id="task-1",
        status=JobStatus.COMPLETED,
        started_at=now,
        completed_at=now,
        error_message=None,
        is_shared=True,
        created_at=now,
        updated_at=now,
    )
    job.user = creator

    response = serialize_data_table_job(job)

    assert response["is_shared"] is True
    assert response["created_by"] == {
        "id": creator.id,
        "display_name": creator.display_name,
    }


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
    assert "ProjectArtifactListResponse" in response_text


def test_clean_baseline_contains_visibility_constraints() -> None:
    baseline = next((ROOT / "server" / "migrations" / "versions").glob("*.py"))
    source = baseline.read_text(encoding="utf-8")
    for constraint in (
        "ck_artifacts_shared_project_scope",
        "ck_audio_overviews_shared_project",
        "ck_data_table_jobs_shared_project",
        "ck_highlights_shared_project",
    ):
        assert constraint in source


def test_public_paper_share_excludes_project_research_layer() -> None:
    # Public shares expose canonical paper data only. Research has no public
    # repository entry point, so an API handler cannot accidentally fetch it.
    assert not hasattr(highlight_crud, "get_public_highlights_data_by_paper_id")
    assert not hasattr(annotation_crud, "get_public_annotations_data_by_paper_id")
