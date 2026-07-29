from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    DurableJob,
    JobDispatch,
    JobOperation,
    JobStatus,
    UploadReservation,
)
from app.modules.papers.infrastructure.upload_lifecycle import (
    UPLOAD_PROCESSING_TIMEOUT,
    UPLOAD_SUBMISSION_TIMEOUT,
    active_upload_freshness_clause,
    reap_stale_uploads,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session


def _result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    return result


def test_upload_freshness_distinguishes_submission_and_processing_windows() -> None:
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    compiled = str(
        active_upload_freshness_clause(now).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "EXISTS (SELECT scholens.job_dispatches.id" in compiled
    assert "NOT (EXISTS (SELECT scholens.job_dispatches.id" in compiled
    assert str(now - UPLOAD_SUBMISSION_TIMEOUT)[:16] in compiled
    assert str(now - UPLOAD_PROCESSING_TIMEOUT)[:16] in compiled


def test_reaper_fails_job_and_schedules_canonical_document_gc() -> None:
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    job_id = uuid4()
    durable_job = DurableJob(
        id=job_id,
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=5,
        idempotency_key=f"pdf-reservation:{job_id}",
        status=JobStatus.PENDING.value,
        payload={},
    )
    durable_job.dispatch = JobDispatch(
        job_id=job_id,
        task_name="upload_and_process_file",
        queue="pdf_processing",
        kwargs={},
    )
    job = UploadReservation(
        id=job_id,
        quota_owner_id=9,
        reference_created=True,
    )
    job.job = durable_job
    digest = "a" * 64
    document = Document(
        id=uuid4(),
        sha256=digest,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{digest}/source.pdf",
        processing_status=DocumentProcessingStatus.PROCESSING.value,
        processing_job_id=job.id,
    )
    durable_job.document_id = document.id
    db = MagicMock(spec=Session)
    db.scalars.return_value = _result([job])
    db.scalar.return_value = document
    schedule_gc = MagicMock()

    with patch(
        "app.modules.papers.infrastructure.garbage_collection.schedule_document_gc",
        schedule_gc,
    ):
        plan = reap_stale_uploads(db, quota_owner_id=9, now=now)

    assert durable_job.status == JobStatus.FAILED.value
    assert durable_job.completed_at == now
    assert durable_job.error_code == "upload_processing_timeout"
    assert plan.storage_keys == ()
    assert document.processing_status == DocumentProcessingStatus.FAILED.value
    assert db.execute.call_count == 1
    db.flush.assert_called_once()
    schedule_gc.assert_called_once_with(db, document_id=document.id)
    db.delete.assert_not_called()


def test_reaper_is_a_noop_when_no_reservation_is_stale() -> None:
    db = MagicMock(spec=Session)
    db.scalars.return_value = _result([])

    plan = reap_stale_uploads(db, quota_owner_id=9)

    assert plan.storage_keys == ()
    db.execute.assert_not_called()
    db.delete.assert_not_called()
