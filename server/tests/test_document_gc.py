"""Reference-safe canonical document collection behavior."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from app.bootstrap.adapters.storage_cleanup import ScheduledStorageDeletion
from app.database.models import Document
from app.bootstrap.adapters.document_gc import collect_document_if_due
from sqlalchemy.orm import Session


def _document(*, gc_after: datetime) -> Document:
    digest = "a" * 64
    return Document(
        id=uuid4(),
        sha256=digest,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{digest}/source.pdf",
        preview_s3_key=f"documents/{digest}/preview.webp",
        gc_after=gc_after,
    )


def test_document_gc_is_cancelled_when_a_reference_reappears() -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [document, True]
    operation_id = uuid4()
    correlation_id = uuid4()

    result = collect_document_if_due(
        db,
        document_id=document.id,
        origin_operation_id=operation_id,
        correlation_id=correlation_id,
        now=now,
    )

    assert result.cancelled is True
    assert result.deleted is False
    assert document.gc_after is None
    db.delete.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_document_gc_schedules_storage_delete_in_the_same_uow(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [document, False]
    db.scalars.return_value.all.return_value = []
    operation_id = uuid4()
    correlation_id = uuid4()
    storage_job_id = uuid4()
    scheduled = MagicMock(
        return_value=ScheduledStorageDeletion(
            job_id=storage_job_id,
            created=True,
        )
    )
    monkeypatch.setattr(
        "app.bootstrap.adapters.document_gc.schedule_storage_deletion",
        scheduled,
    )

    result = collect_document_if_due(
        db,
        document_id=document.id,
        origin_operation_id=operation_id,
        correlation_id=correlation_id,
        now=now,
    )

    assert result.deleted is True
    assert result.storage_deletion == ScheduledStorageDeletion(
        job_id=storage_job_id,
        created=True,
    )
    scheduled.assert_called_once()
    call = scheduled.call_args
    assert set(call.kwargs["object_keys"]) == {
        document.s3_object_key,
        document.preview_s3_key,
    }
    assert call.kwargs["origin_operation_id"] == operation_id
    assert call.kwargs["correlation_id"] == correlation_id
    db.delete.assert_called_once_with(document)
    db.flush.assert_called_once()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()
