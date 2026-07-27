from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from app.database.models import Document, JobStatus, PaperUploadJob
from app.services.upload_lifecycle import (
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

    assert "paper_upload_jobs.task_id IS NULL" in compiled
    assert "paper_upload_jobs.task_id IS NOT NULL" in compiled
    assert str(now - UPLOAD_SUBMISSION_TIMEOUT)[:16] in compiled
    assert str(now - UPLOAD_PROCESSING_TIMEOUT)[:16] in compiled


def test_reaper_fails_job_and_removes_placeholder_document_atomically() -> None:
    now = datetime(2026, 7, 27, tzinfo=timezone.utc)
    job = PaperUploadJob(
        id=uuid4(),
        user_id=5,
        quota_owner_id=9,
        status=JobStatus.PENDING,
        task_id="deterministic-task-id",
    )
    document = Document(
        id=uuid4(),
        file_url="s3://bucket/paper.pdf",
        s3_object_key="papers/paper.pdf",
        parser_archive_s3_key="parses/paper.zip",
        upload_job_id=job.id,
    )
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [
        _result([job]),
        _result([document]),
        _result(["images/page.png"]),
    ]

    plan = reap_stale_uploads(db, quota_owner_id=9, now=now)

    assert job.status == JobStatus.FAILED
    assert job.completed_at == now
    assert job.error_code == "upload_processing_timeout"
    assert set(plan.storage_keys) == {
        "papers/paper.pdf",
        "parses/paper.zip",
        "images/page.png",
    }
    assert db.execute.call_count == 2
    db.flush.assert_called_once()
    db.delete.assert_called_once_with(document)


def test_reaper_is_a_noop_when_no_reservation_is_stale() -> None:
    db = MagicMock(spec=Session)
    db.scalars.return_value = _result([])

    plan = reap_stale_uploads(db, quota_owner_id=9)

    assert plan.storage_keys == ()
    db.execute.assert_not_called()
    db.delete.assert_not_called()
