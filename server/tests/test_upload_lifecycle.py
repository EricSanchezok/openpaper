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
    LibraryPaper,
)
from app.bootstrap.adapters.document_gc import ScheduledDocumentGc
from app.bootstrap.adapters.upload_lifecycle import (
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
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
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
    library_reference = MagicMock(spec=LibraryPaper)
    db.scalar.side_effect = [library_reference, document]
    gc_job_id = uuid4()
    schedule_gc = MagicMock(
        return_value=ScheduledDocumentGc(job_id=gc_job_id, created=True)
    )
    origin_operation_id = uuid4()
    correlation_id = uuid4()

    with patch(
        "app.bootstrap.adapters.document_gc.schedule_document_gc",
        schedule_gc,
    ):
        reaped = reap_stale_uploads(
            db,
            quota_owner_id=9,
            origin_operation_id=origin_operation_id,
            correlation_id=correlation_id,
            now=now,
        )

    assert durable_job.status == JobStatus.FAILED.value
    assert durable_job.completed_at == now
    assert durable_job.error_code == "upload_processing_timeout"
    assert document.processing_status == DocumentProcessingStatus.FAILED.value
    assert len(reaped) == 1
    assert reaped[0].job_id == job_id
    assert reaped[0].reference_removed
    assert reaped[0].document_processing_failed
    assert reaped[0].created_gc_job_id == gc_job_id
    assert db.flush.call_count == 2
    schedule_gc.assert_called_once_with(
        db,
        document_id=document.id,
        origin_operation_id=origin_operation_id,
        correlation_id=correlation_id,
    )
    db.delete.assert_called_once_with(library_reference)


def test_reaper_is_a_noop_when_no_reservation_is_stale() -> None:
    db = MagicMock(spec=Session)
    db.scalars.return_value = _result([])

    result = reap_stale_uploads(
        db,
        quota_owner_id=9,
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert result == ()
    db.execute.assert_not_called()
    db.delete.assert_not_called()
