from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.database.models import (
    DurableJob,
    JobDispatch,
    JobDispatchStatus,
    JobOperation,
    JobStatus,
)
from app.modules.jobs.infrastructure.repository import (
    ReservedJobDispatch,
    job_repository,
)
from app.modules.jobs.infrastructure.dispatcher import dispatch_pending_jobs_once
from sqlalchemy.orm import Session


def _job(*, status: JobStatus = JobStatus.PENDING) -> DurableJob:
    job_id = uuid4()
    return DurableJob(
        id=job_id,
        operation=JobOperation.AUDIO_GENERATE.value,
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        requested_by_id=7,
        idempotency_key=f"audio:{job_id}",
        status=status.value,
        payload={},
    )


def test_duplicate_completion_cannot_apply_side_effects_twice() -> None:
    job = _job(status=JobStatus.COMPLETED)
    db = MagicMock(spec=Session)
    db.scalar.return_value = job

    returned, changed = job_repository.complete(
        db,
        job_id=job.id,
        result={"research_item_id": str(uuid4())},
    )

    assert returned is job
    assert changed is False
    db.flush.assert_not_called()


def test_failed_job_is_terminal_and_cannot_complete_later() -> None:
    job = _job(status=JobStatus.FAILED)
    db = MagicMock(spec=Session)
    db.scalar.return_value = job

    returned, changed = job_repository.complete(
        db,
        job_id=job.id,
        result={"late": True},
    )

    assert returned is job
    assert changed is False
    assert job.status == JobStatus.FAILED.value
    db.flush.assert_not_called()


def test_expired_worker_lease_requeues_the_existing_dispatch() -> None:
    job = _job(status=JobStatus.RUNNING)
    job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    dispatch = JobDispatch(
        job_id=job.id,
        task_name="generate_audio_overview",
        queue="audio",
        kwargs={},
        status=JobDispatchStatus.PUBLISHED.value,
        published_at=datetime.now(UTC),
    )
    job.dispatch = dispatch
    result = MagicMock()
    result.all.return_value = [job]
    db = MagicMock(spec=Session)
    db.scalars.return_value = result

    recovered = job_repository.recover_expired_leases(db, limit=10)

    assert recovered == 1
    assert job.status == JobStatus.PENDING.value
    assert dispatch.status == JobDispatchStatus.PENDING.value
    assert dispatch.published_at is None
    db.flush.assert_called_once()


def test_publish_failure_keeps_dispatch_pending_for_retry() -> None:
    job = _job()
    dispatch = ReservedJobDispatch(
        dispatch_id=uuid4(),
        job_id=job.id,
        task_name="generate_audio_overview",
        queue="audio",
        kwargs={"request": {}},
        attempt_count=1,
        enqueued_at=datetime.now(UTC),
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
        requested_by_id=42,
    )

    with (
        patch(
            "app.modules.jobs.infrastructure.dispatcher._reserve_dispatches",
            return_value=(dispatch,),
        ),
        patch(
            "app.modules.jobs.infrastructure.dispatcher._record_publish_failure",
            return_value=True,
        ) as record_failure,
        patch(
            "app.modules.jobs.infrastructure.dispatcher._record_publish_success",
            return_value=True,
        ),
        patch(
            "app.modules.jobs.infrastructure.dispatcher.jobs_client.publish_task",
            side_effect=RuntimeError("jobs_broker_unavailable"),
        ),
    ):
        published = dispatch_pending_jobs_once()

    assert published == 0
    assert dispatch.attempt_count == 1
    record_failure.assert_called_once()


def test_dispatch_reservation_uses_a_versioned_publishing_lease() -> None:
    job = _job()
    dispatch = JobDispatch(
        job=job,
        job_id=job.id,
        task_name="generate_audio_overview",
        queue="audio",
        kwargs={"request": {}},
        status=JobDispatchStatus.PENDING.value,
        available_at=datetime.now(UTC),
        attempt_count=0,
    )
    db = MagicMock(spec=Session)
    db.scalars.return_value.all.return_value = [dispatch]
    lease = timedelta(seconds=30)

    reserved = job_repository.reserve_dispatches(db, limit=10, lease=lease)

    assert len(reserved) == 1
    assert reserved[0].dispatch_id == dispatch.id
    assert reserved[0].attempt_count == 1
    assert dispatch.status == JobDispatchStatus.PUBLISHING.value
    assert dispatch.attempt_count == 1
    assert dispatch.available_at > datetime.now(UTC)
    db.flush.assert_called_once()
