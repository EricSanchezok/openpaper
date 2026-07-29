"""Contracts for the lightweight project collaboration model."""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from app.transport.http.public_v1.projects.documents import AddPaperToProjectRequest
from app.bootstrap.adapters.project_documents import (
    project_document_repository,
)
from app.database.models import (
    Base,
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
    UploadReservation,
)
from app.shared.domain import AppError
from app.main import app
from app.modules.projects.infrastructure.access import ProjectAccess, ProjectPermissions
from app.bootstrap.adapters.project_repository import project_repository
from app.modules.projects.application.contracts import (
    ProjectInvitationCreateRequest,
    ProjectPermissionSet,
)
from app.shared.application import Actor
from pydantic import ValidationError
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[2]


def _document(document_id: uuid.UUID, *, size_kb: int, seed: str) -> Document:
    digest = seed * 64
    return Document(
        id=document_id,
        sha256=digest,
        original_filename=f"{seed}.pdf",
        mime_type="application/pdf",
        size_bytes=size_kb * 1024,
        s3_object_key=f"documents/{digest}/source.pdf",
    )


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


def test_collaborator_cannot_grant_or_manage_permissions_they_do_not_have(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(id=uuid.uuid4(), owner_id=1, title="Project")
    actor_membership = ProjectCollaborator(
        project_id=project.id,
        user_id=2,
        can_manage_collaborators=True,
    )
    actor = ProjectAccess(
        project=project,
        user_id=2,
        is_owner=False,
        collaborator=actor_membership,
        permissions=ProjectPermissions(manage_collaborators=True),
    )
    target = ProjectCollaborator(
        project_id=project.id,
        user_id=3,
        can_manage_papers=True,
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = target
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_repository.require_project_permission",
        lambda *_args, **_kwargs: actor,
    )

    with pytest.raises(AppError) as exc_info:
        project_repository.update_collaborator(
            db,
            project_id=project.id,
            actor_id=2,
            target_user_id=3,
            requested=ProjectPermissionSet(manage_papers=True),
        )

    assert exc_info.value.code == "project_permission_escalation"
    db.commit.assert_not_called()

    with pytest.raises(AppError) as exc_info:
        project_repository.remove_collaborator(
            db,
            project_id=project.id,
            actor_id=2,
            target_user_id=3,
        )

    assert exc_info.value.code == "project_collaborator_not_manageable"
    db.delete.assert_not_called()


def test_project_requests_reject_legacy_roles_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectInvitationCreateRequest.model_validate(
            {
                "email": "collaborator@example.com",
                "role": "admin",
            }
        )

    document_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        AddPaperToProjectRequest.model_validate(
            {"document_ids": [str(document_id), str(document_id)]}
        )
    with pytest.raises(ValidationError):
        AddPaperToProjectRequest.model_validate({"document_ids": []})


def test_project_papers_are_attached_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    project = Project(id=uuid.uuid4(), owner_id=1, title="Project")
    documents = [
        _document(uuid.uuid4(), size_kb=100, seed="a"),
        _document(uuid.uuid4(), size_kb=200, seed="b"),
    ]
    empty_result = MagicMock()
    empty_result.all.return_value = []
    document_result = MagicMock()
    document_result.all.return_value = documents
    db.scalar.return_value = project
    db.scalars.side_effect = [empty_result, document_result]

    monkeypatch.setattr(
        "app.bootstrap.adapters.project_documents.require_project_permission",
        lambda *_args, **_kwargs: None,
    )
    quota_check = MagicMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_documents.require_project_document_capacity",
        quota_check,
    )

    associations, existing_count = project_document_repository.attach_library_documents(
        db,
        document_ids=[document.id for document in documents],
        project_id=project.id,
        user=Actor(
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
    gc_update = str(db.execute.call_args.args[0])
    assert "gc_after" in gc_update
    assert "NULL" in gc_update
    db.commit.assert_not_called()
    db.flush.assert_called()


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
        _document(requested_ids[0], size_kb=100, seed="a")
    ]
    db.scalar.return_value = project
    db.scalars.side_effect = [empty_result, partial_result]
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_documents.require_project_permission",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(AppError) as exc_info:
        project_document_repository.attach_library_documents(
            db,
            document_ids=requested_ids,
            project_id=project.id,
            user=Actor(
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


def test_fresh_project_upload_requires_matching_durable_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    job_id = uuid.uuid4()
    project_id = uuid.uuid4()
    durable_job = DurableJob(
        id=job_id,
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=2,
        project_id=project_id,
        idempotency_key=f"pdf-reservation:{job_id}",
        status=JobStatus.PENDING.value,
        payload={},
    )
    upload_job = UploadReservation(
        id=job_id,
        quota_owner_id=1,
        original_filename="a.pdf",
        reserved_reference_count=1,
        reserved_size_kb=100,
    )
    upload_job.job = durable_job
    document = _document(uuid.uuid4(), size_kb=100, seed="a")
    db.scalar.return_value = None
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_documents.require_project_permission",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(AppError) as error:
        project_document_repository.attach_reserved_upload(
            db,
            document=document,
            upload_job=upload_job,
            project_id=project_id,
            user=Actor(
                id=2,
                email="collaborator@example.com",
                status="active",
                email_verified=True,
                is_active=True,
            ),
        )

    assert error.value.code == "upload_reservation_invalid"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_transfer_validates_and_reassigns_owner_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Project(id=uuid.uuid4(), owner_id=1, title="Project")
    new_owner_membership = ProjectCollaborator(
        project_id=project.id,
        user_id=2,
        can_manage_papers=True,
    )
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [project, new_owner_membership]
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_repository.require_project_permission",
        lambda *_args, **_kwargs: None,
    )
    quota_reassignment = MagicMock()
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_repository.reassign_project_quota_owner",
        quota_reassignment,
    )

    transferred = project_repository.transfer(
        db,
        project_id=project.id,
        owner_id=1,
        new_owner_id=2,
    )

    quota_reassignment.assert_called_once_with(
        db,
        project=project,
        new_owner_id=2,
    )
    assert transferred.owner_id == 2
    db.delete.assert_called_once_with(new_owner_membership)
    db.commit.assert_not_called()
    db.flush.assert_called()


def _invitation(
    *,
    project_id: uuid.UUID,
    invited_by_id: int = 1,
    email: str = "collaborator@example.com",
) -> ProjectInvitation:
    return ProjectInvitation(
        id=uuid.uuid4(),
        project_id=project_id,
        email=email,
        token_hash="a" * 64,
        invited_by_id=invited_by_id,
        can_manage_papers=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )


def test_invitation_revalidates_inviter_before_accepting_existing_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid.uuid4()
    invitation = _invitation(project_id=project_id, invited_by_id=5)
    db = MagicMock(spec=Session)
    db.get.return_value = Project(id=project_id, owner_id=1, title="Project")
    monkeypatch.setattr(
        "app.bootstrap.adapters.project_repository.get_project_access",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(AppError) as exc_info:
        project_repository._accept_invitation(
            db,
            invitation=invitation,
            user_id=2,
            email=invitation.email,
        )

    assert exc_info.value.code == "project_invitation_authority_revoked"
    assert invitation.accepted_at is None
    db.commit.assert_not_called()


@pytest.mark.parametrize(
    ("mutate", "email"),
    [
        (
            lambda invitation: setattr(
                invitation, "revoked_at", datetime.now(timezone.utc)
            ),
            "collaborator@example.com",
        ),
        (
            lambda invitation: setattr(
                invitation,
                "expires_at",
                datetime.now(timezone.utc) - timedelta(seconds=1),
            ),
            "collaborator@example.com",
        ),
        (lambda _invitation: None, "another@example.com"),
    ],
)
def test_invalid_invitation_states_fail_without_side_effects(
    mutate: object,
    email: str,
) -> None:
    project_id = uuid.uuid4()
    invitation = _invitation(project_id=project_id)
    assert callable(mutate)
    mutate(invitation)
    db = MagicMock(spec=Session)

    with pytest.raises(AppError) as exc_info:
        project_repository._accept_invitation(
            db,
            invitation=invitation,
            user_id=2,
            email=email,
        )

    assert exc_info.value.code == "project_invitation_invalid"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_project_api_exposes_capabilities_and_invitation_lifecycle() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/projects/{project_id}/members" in paths
    assert "/api/v1/projects/{project_id}/collaborators" not in paths
    assert "/api/v1/projects/{project_id}/transfer" in paths
    assert "/api/v1/projects/{project_id}/leave" in paths
    assert "/api/v1/projects/{project_id}/papers" in paths
    assert "/api/v1/projects/{project_id}/papers/{document_id}" in paths
    assert "/api/v1/project-invitations/{token}/accept" in paths
    assert "/api/v1/project-invitations/token/{token}/accept" not in paths
    assert not any("role" in path for path in paths if "project" in path)


def test_document_and_library_api_expose_canonical_asset_boundaries() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/library/papers" in paths
    assert "/api/v1/library/papers/{document_id}" in paths
    assert "/api/v1/library/papers/{document_id}/share" in paths
    assert "/api/v1/papers/{document_id}" in paths
    assert "/api/v1/papers/{document_id}/download-url" in paths
    assert "/api/v1/papers/{document_id}/research-items" in paths
    assert "/api/v1/shares/{share_token}" in paths
    assert "/api/v1/shares/{share_token}/collect" in paths
    assert not any("{library_paper_id}" in path for path in paths)
    assert "/api/v1/paper" not in paths


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

    baseline = sorted((ROOT / "server" / "migrations" / "versions").glob("*.py"))[0]
    source = baseline.read_text(encoding="utf-8")
    for table_name in expected:
        assert f'"{table_name.removeprefix("scholens.")}"' in source
    for table_name in removed:
        assert f'"{table_name.removeprefix("scholens.")}"' not in source
