"""Contracts for the lightweight project collaboration model."""

from pathlib import Path

import pytest
from app.database.models import Base
from app.main import app
from app.policies.projects import ProjectPermissions
from app.schemas.projects import ProjectInvitationCreateRequest
from pydantic import ValidationError

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
