"""Reference-safe canonical document collection behavior."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from app.database.models import Document
from app.services.document_gc import collect_document_if_due
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


def test_document_gc_is_cancelled_when_a_reference_reappears(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [document, True]
    delete_files = MagicMock()
    monkeypatch.setattr(
        "app.services.document_gc.s3_service.delete_files",
        delete_files,
    )

    result = collect_document_if_due(db, document_id=document.id, now=now)

    assert result.cancelled is True
    assert result.deleted is False
    assert document.gc_after is None
    delete_files.assert_not_called()
    db.delete.assert_not_called()
    db.commit.assert_called_once()


def test_document_gc_retries_without_deleting_database_state_on_s3_failure(
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    document = _document(gc_after=now - timedelta(minutes=1))
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [document, False]
    db.scalars.return_value.all.return_value = []
    monkeypatch.setattr(
        "app.services.document_gc.s3_service.delete_files",
        MagicMock(return_value=[document.s3_object_key]),
    )

    result = collect_document_if_due(db, document_id=document.id, now=now)

    assert result.retry_required is True
    assert result.deleted is False
    db.rollback.assert_called_once()
    db.delete.assert_not_called()
    db.commit.assert_not_called()
