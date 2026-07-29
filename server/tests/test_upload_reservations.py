from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from app.database.models import (
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    Project,
    SubscriptionPlan,
    UploadReservation,
)
from app.shared.domain import AppError
from app.bootstrap.adapters.upload_reservations import (
    reassign_project_quota_owner,
    reserve_upload,
)


def _quota_patches(*, active_count: int = 0, active_size_kb: int = 0):
    return (
        patch(
            "app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_quota_user",
            return_value=MagicMock(),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_user_subscription_plan",
            return_value=SubscriptionPlan.BASIC,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._active_account_reservations",
            return_value=(active_count, active_size_kb),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.completed_reference_count",
            return_value=0,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._has_active_duplicate_reservation",
            return_value=False,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.completed_storage_kb",
            return_value=0,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.reap_stale_uploads",
            return_value=None,
        ),
    )


def _durable_job(*, requester_id: int, project_id=None) -> DurableJob:
    job_id = uuid4()
    return DurableJob(
        id=job_id,
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=requester_id,
        project_id=project_id,
        idempotency_key=f"pdf-reservation:{job_id}",
        status=JobStatus.PENDING.value,
        payload={},
    )


def test_personal_upload_is_reserved_to_requester() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    requester = MagicMock(id=17)
    durable_job = _durable_job(requester_id=17)
    patches = _quota_patches()

    with (
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.create",
            return_value=durable_job,
        ),
    ):
        job = reserve_upload(
            db,
            requester=requester,
            project_id=None,
            input_size_bytes=1_025,
            original_filename="paper.pdf",
            content_sha256="a" * 64,
        )

    assert job.job.requested_by_id == 17
    assert job.quota_owner_id == 17
    assert job.job.project_id is None
    assert job.reserved_size_kb == 2
    assert job.job.status == JobStatus.PENDING.value
    quota_lock.assert_called_once_with(db, user_id=17)
    db.add.assert_called_once_with(job)
    db.flush.assert_called_once()
    db.commit.assert_not_called()


def test_project_upload_is_billed_to_owner_not_collaborator() -> None:
    project_id = uuid4()
    project = Project(id=project_id, title="Shared corpus", owner_id=91)
    db = MagicMock()
    db.scalar.side_effect = [project, None, 3]
    requester = MagicMock(id=17)
    durable_job = _durable_job(requester_id=17, project_id=project_id)
    patches = _quota_patches()

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.require_project_permission"
        ) as permission,
        patch(
            "app.bootstrap.adapters.upload_reservations._unattached_project_reservations",
            return_value=2,
        ),
        patches[0] as quota_lock,
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
        patches[7],
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.create",
            return_value=durable_job,
        ),
    ):
        job = reserve_upload(
            db,
            requester=requester,
            project_id=project_id,
            input_size_bytes=4_096,
            original_filename="shared.pdf",
            content_sha256="b" * 64,
        )

    permission.assert_called_once_with(
        db,
        project_id=project_id,
        user_id=17,
        permission="manage_papers",
    )
    quota_lock.assert_called_once_with(db, user_id=91)
    assert job.job.requested_by_id == 17
    assert job.quota_owner_id == 91
    assert job.job.project_id == project_id


def test_active_reservations_prevent_concurrent_paper_quota_bypass() -> None:
    db = MagicMock()
    db.scalar.return_value = None
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
        patches[7],
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=requester,
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            content_sha256="c" * 64,
        )

    assert error.value.code == "paper_quota_exceeded"
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_same_document_cannot_be_reserved_twice_for_one_library() -> None:
    db = MagicMock()
    db.scalar.return_value = None
    requester = MagicMock(id=17)
    patches = _quota_patches()

    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patch(
            "app.bootstrap.adapters.upload_reservations._has_active_duplicate_reservation",
            return_value=True,
        ),
        patches[6],
        patches[7],
        pytest.raises(AppError) as error,
    ):
        reserve_upload(
            db,
            requester=requester,
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            content_sha256="c" * 64,
        )

    assert error.value.code == "document_upload_in_progress"
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
            content_sha256="d" * 64,
        )

    assert error.value.code == "empty_upload"
    db.execute.assert_not_called()
    db.add.assert_not_called()


def test_idempotency_key_returns_the_original_reservation() -> None:
    requester = MagicMock(id=17)
    existing_job = _durable_job(requester_id=17)
    existing_job.idempotency_key = "pdf-ingestion:17:library:request-1"
    existing_job.payload = {"content_sha256": "e" * 64}
    reservation = UploadReservation(
        id=existing_job.id,
        quota_owner_id=17,
        content_sha256="e" * 64,
    )
    reservation.job = existing_job
    db = MagicMock()
    db.get.return_value = reservation

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.job_repository.find_by_idempotency_key",
            return_value=existing_job,
        ),
    ):
        result = reserve_upload(
            db,
            requester=requester,
            project_id=None,
            input_size_bytes=1_024,
            original_filename="paper.pdf",
            content_sha256="e" * 64,
            idempotency_key="request-1",
        )

    assert result is reservation
    db.add.assert_not_called()


def test_project_transfer_accounts_for_documents_and_active_reservations() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    digest = "e" * 64
    incremental = Document(
        id=uuid4(),
        sha256=digest,
        original_filename="completed.pdf",
        mime_type="application/pdf",
        size_bytes=100 * 1024,
        s3_object_key=f"documents/{digest}/source.pdf",
    )
    db = MagicMock()
    db.scalar.side_effect = [1, 4]
    project_active_usage = MagicMock()
    project_active_usage.one.return_value = (2, 60)
    reassignment_result = MagicMock()
    db.execute.side_effect = [project_active_usage, reassignment_result]
    documents = MagicMock()
    documents.all.return_value = [incremental]
    db.scalars.return_value = documents

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"
        ) as quota_lock,
        patch(
            "app.bootstrap.adapters.upload_reservations.get_quota_user",
            return_value=MagicMock(),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_user_subscription_plan",
            return_value=SubscriptionPlan.BASIC,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations._active_account_reservations",
            return_value=(1, 40),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.completed_reference_count",
            return_value=2,
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.resource_usage_repository.completed_storage_kb",
            return_value=200,
        ),
    ):
        reassign_project_quota_owner(db, project=project, new_owner_id=20)

    quota_lock.assert_called_once_with(db, user_id=20)
    assert db.execute.call_count == 2


def test_project_transfer_rejects_new_owner_project_limit() -> None:
    project = Project(id=uuid4(), title="Shared corpus", owner_id=10)
    db = MagicMock()
    db.scalar.return_value = 2

    with (
        patch(
            "app.bootstrap.adapters.upload_reservations.lock_account_resource_quota"
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_quota_user",
            return_value=MagicMock(),
        ),
        patch(
            "app.bootstrap.adapters.upload_reservations.get_user_subscription_plan",
            return_value=SubscriptionPlan.BASIC,
        ),
        pytest.raises(AppError) as error,
    ):
        reassign_project_quota_owner(db, project=project, new_owner_id=20)

    assert error.value.code == "project_transfer_quota_exceeded"
    db.execute.assert_not_called()
