"""Contracts for the lightweight project collaboration model."""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app.api.projects.project_papers_api import AddPaperToProjectRequest
from app.database.crud.projects.project_paper_crud import project_paper_crud
from app.database.models import Base, Document, Project, ProjectPaper
from app.errors import AppError
from app.main import app
from app.policies.projects import ProjectPermissions
from app.schemas.projects import ProjectInvitationCreateRequest
from app.schemas.user import CurrentUser
from pydantic import ValidationError
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[2]


def test_project_permission_sets_only_contain_their_own_powers() -> None:
    paper_manager = ProjectPermissions(manage_papers=True)
    collaborator_manager = ProjectPermissions(
        manage_papers=True,
        manage_collaborators=True,
    )

    assert paper_manager.contains(ProjectPermissions())
    assert paper_manager.contains(ProjectPermissions(manage_papers=True))
    assert not paper_manager.contains(ProjectPermissions(manage_collaborators=True))
    assert collaborator_manager.contains(paper_manager)
    assert ProjectPermissions.all().contains(collaborator_manager)


def test_project_requests_reject_legacy_roles_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectInvitationCreateRequest.model_validate(
            {
                "email": "collaborator@example.com",
                "role": "admin",
            }
        )

    paper_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        AddPaperToProjectRequest.model_validate(
            {"paper_ids": [str(paper_id), str(paper_id)]}
        )
    with pytest.raises(ValidationError):
        AddPaperToProjectRequest.model_validate({"paper_ids": []})


def test_project_papers_are_attached_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    project = Project(id=uuid.uuid4(), owner_id=1, title="Project")
    documents = [
        Document(id=uuid.uuid4(), file_url="s3://bucket/a.pdf", size_in_kb=100),
        Document(id=uuid.uuid4(), file_url="s3://bucket/b.pdf", size_in_kb=200),
    ]
    empty_result = MagicMock()
    empty_result.all.return_value = []
    document_result = MagicMock()
    document_result.all.return_value = documents
    db.scalar.return_value = project
    db.scalars.side_effect = [empty_result, document_result]

    monkeypatch.setattr(
        "app.database.crud.projects.project_paper_crud.require_project_permission",
        lambda *_args, **_kwargs: None,
    )
    quota_check = MagicMock()
    monkeypatch.setattr(
        "app.database.crud.projects.project_paper_crud.require_project_document_capacity",
        quota_check,
    )

    associations, existing_count = project_paper_crud.attach_library_documents(
        db,
        document_ids=[document.id for document in documents],
        project_id=project.id,
        user=CurrentUser(
            id=2,
            email="collaborator@example.com",
            status="active",
            email_verified=True,
            is_active=True,
        ),
    )

    assert len(associations) == 2
    assert existing_count == 0
    assert all(isinstance(item, ProjectPaper) for item in associations)
    quota_check.assert_called_once()
    db.add_all.assert_called_once_with(associations)
    db.commit.assert_called_once()


def test_project_paper_batch_rejects_partial_library_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    project = Project(id=uuid.uuid4(), owner_id=1, title="Project")
    requested_ids = [uuid.uuid4(), uuid.uuid4()]
    empty_result = MagicMock()
    empty_result.all.return_value = []
    partial_result = MagicMock()
    partial_result.all.return_value = [
        Document(id=requested_ids[0], file_url="s3://bucket/a.pdf", size_in_kb=100)
    ]
    db.scalar.return_value = project
    db.scalars.side_effect = [empty_result, partial_result]
    monkeypatch.setattr(
        "app.database.crud.projects.project_paper_crud.require_project_permission",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(AppError) as exc_info:
        project_paper_crud.attach_library_documents(
            db,
            document_ids=requested_ids,
            project_id=project.id,
            user=CurrentUser(
                id=2,
                email="collaborator@example.com",
                status="active",
                email_verified=True,
                is_active=True,
            ),
        )

    assert exc_info.value.code == "library_document_not_found"
    db.add_all.assert_not_called()
    db.commit.assert_not_called()


def test_project_api_exposes_capabilities_and_invitation_lifecycle() -> None:
    paths = app.openapi()["paths"]

    assert "/api/projects/{project_id}/members" in paths
    assert "/api/projects/{project_id}/transfer" in paths
    assert "/api/projects/{project_id}/leave" in paths
    assert "/api/project-invitations/{invitation_id}/accept" in paths
    assert "/api/project-invitations/{invitation_id}" in paths
    assert "/api/project-invitations/token/{token}/accept" in paths
    assert not any("role" in path for path in paths if "project" in path)


def test_metadata_and_baseline_have_only_the_new_project_tables() -> None:
    tables = set(Base.metadata.tables)
    expected = {
        "scholens.projects",
        "scholens.project_collaborators",
        "scholens.project_invitations",
        "scholens.project_papers",
    }
    removed = {
        "scholens.project",
        "scholens.project_role",
        "scholens.project_role_invitations",
        "scholens.project_audio_overview",
        "scholens.project_paper",
    }

    assert expected <= tables
    assert removed.isdisjoint(tables)

    baseline = next((ROOT / "server" / "migrations" / "versions").glob("*.py"))
    source = baseline.read_text(encoding="utf-8")
    for table_name in expected:
        assert f'"{table_name.removeprefix("scholens.")}"' in source
    for table_name in removed:
        assert f'"{table_name.removeprefix("scholens.")}"' not in source
