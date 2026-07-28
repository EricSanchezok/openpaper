"""Durable callback boundaries always settle transactional resources."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.errors import AppError
from app.services.callback_boundaries import (
    callback_transaction,
    optional_savepoint,
    pdf_ingestion_callback,
)
from sqlalchemy.orm import Session


def test_callback_transaction_rolls_back_and_releases_lock() -> None:
    db = MagicMock(spec=Session)
    lock = MagicMock()

    with pytest.raises(RuntimeError, match="failed"):
        with callback_transaction(
            db,
            operation="test",
            context={"job_id": "job"},
            lock=lock,
        ):
            raise RuntimeError("failed")

    db.rollback.assert_called_once()
    lock.release.assert_called_once()


def test_optional_savepoint_contains_failure() -> None:
    db = MagicMock(spec=Session)
    savepoint = MagicMock()
    db.begin_nested.return_value = savepoint

    with optional_savepoint(db, operation="optional", context={}):
        raise RuntimeError("optional failure")

    savepoint.__exit__.assert_called_once()


@pytest.mark.asyncio
async def test_pdf_callback_failure_cleans_up_and_releases_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    lock = MagicMock()
    cleanup = MagicMock(side_effect=RuntimeError("cleanup failed"))
    fallback = MagicMock()
    release = AsyncMock()
    monkeypatch.setattr(
        "app.services.callback_boundaries.release_concurrency_by_id",
        release,
    )

    with pytest.raises(AppError) as exc_info:
        async with pdf_ingestion_callback(
            db,
            lock=lock,
            user_id=7,
            operation_id="job",
            cleanup=cleanup,
            fallback_mark_failed=fallback,
        ):
            raise RuntimeError("apply failed")

    assert exc_info.value.code == "pdf_webhook_failed"
    db.rollback.assert_called_once()
    cleanup.assert_called_once()
    fallback.assert_called_once()
    lock.release.assert_called_once()
    release.assert_awaited_once_with(
        user_id=7,
        category="background",
        operation_id="job",
    )
