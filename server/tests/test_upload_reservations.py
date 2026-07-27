from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.database.models import JobStatus, Project, SubscriptionPlan
from app.errors import AppError
from app.services.upload_reservations import reserve_upload


def _quota_patches(*, active_count: int = 0, active_size_kb: int = 0):
    return (
        patch("app.services.upload_reservations.lock_account_resource_quota"),
        patch(
            "app.services.upload_reservations.get_quota_user",
            return_value=MagicMock(),
        ),
        patch(
            "app.services.upload_reservations.get_user_subscription_plan",
            return_value=SubscriptionPlan.BASIC,
        ),
        patch(
            "app.services.upload_reservations._active_account_reservations",
            return_value=(active_count, active_size_kb),
        ),
        patch(
            "app.services.upload_reservations.paper_crud.get_total_paper_count",
            return_value=0,
        ),
        patch(
            "app.services.upload_reservations.paper_crud.has_unknown_billed_document_size",
            return_value=False,
        ),
        patch(
            "app.services.upload_reservations.paper_crud.get_size_of_knowledge_base",
            return_value=0,
        ),
    )


def test_personal_upload_is_reserved_to_requester() -> None:
    db = MagicMock()
    requester = MagicMock(id=17)
    patches = _quota_patches()

    with (
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        job = reserve_upload(
            db,
            requester=requester,
            project_id=None,
            input_size_bytes=1_025,
            original_filename="paper.pdf",
        )

    assert job.user_id == 17
    assert job.quota_owner_id == 17
    assert job.project_id is None
    assert job.reserved_size_kb == 2
    assert job.status == JobStatus.PENDING
    quota_lock.assert_called_once_with(db, user_id=17)
    db.add.assert_called_once_with(job)
    db.commit.assert_called_once()


def test_project_upload_is_billed_to_owner_not_collaborator() -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Shared corpus", owner_id=91)
    db = MagicMock()
    db.scalar.side_effect = [project, 3]
    requester = MagicMock(id=17)
    patches = _quota_patches()

    with (
        patch(
            "app.services.upload_reservations.require_project_permission"
        ) as permission,
        patch(
            "app.services.upload_reservations._unattached_project_reservations",
            return_value=2,
        ),
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        job = reserve_upload(
            db,
            requester=requester,
            project_id=project_id,
            input_size_bytes=4_096,
            original_filename="shared.pdf",
        )

    permission.assert_called_once_with(
        db,
        project_id=project_id,
        user_id=17,
        permission="manage_papers",
    )
    quota_lock.assert_called_once_with(db, user_id=91)
    assert job.user_id == 17
    assert job.quota_owner_id == 91
    assert job.project_id == project_id


def test_active_reservations_prevent_concurrent_paper_quota_bypass() -> None:
    db = MagicMock()
    requester = MagicMock(id=17)
    patches = _quota_patches(active_count=10)

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=requester,
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
        )

    assert error.value.code == "paper_quota_exceeded"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_empty_upload_is_rejected_before_any_reservation() -> None:
    db = MagicMock()

    with pytest.raises(AppError) as error:
        reserve_upload(
            db,
            requester=MagicMock(id=17),
            project_id=None,
            input_size_bytes=0,
            original_filename="empty.pdf",
        )

    assert error.value.code == "empty_upload"
    db.execute.assert_not_called()
    db.add.assert_not_called()
