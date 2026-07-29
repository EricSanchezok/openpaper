"""Transaction and cleanup boundaries for durable callback handlers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager

from app.shared.domain import AppError
from app.helpers.advisory_locks import AdvisoryLock
from app.helpers.ai_limits import release_concurrency_by_id
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@contextmanager
def optional_savepoint(
    db: Session,
    *,
    operation: str,
    context: dict[str, object],
) -> Iterator[None]:
    """Isolate an optional side effect without corrupting the outer transaction."""
    try:
        with db.begin_nested():
            yield
    except Exception:
        logger.exception(
            "Optional callback side effect failed",
            extra={"operation": operation, **context},
        )


@contextmanager
def callback_transaction(
    db: Session,
    *,
    operation: str,
    context: dict[str, object],
    lock: AdvisoryLock | None = None,
) -> Iterator[None]:
    """Rollback and release an optional advisory lock on callback failure."""
    try:
        yield
    except Exception:
        db.rollback()
        logger.exception(
            "Durable callback transaction failed",
            extra={"operation": operation, **context},
        )
        raise
    finally:
        if lock is not None:
            lock.release()


@asynccontextmanager
async def pdf_ingestion_callback(
    db: Session,
    *,
    lock: AdvisoryLock,
    user_id: int,
    operation_id: str,
    cleanup: Callable[[], None],
    fallback_mark_failed: Callable[[], None],
) -> AsyncIterator[None]:
    """Guarantee rollback, cleanup, lock release, and lease settlement."""
    try:
        yield
    except Exception as exc:
        db.rollback()
        logger.exception(
            "PDF ingestion callback failed",
            extra={"job_id": operation_id},
        )
        try:
            cleanup()
        except Exception:
            logger.exception(
                "PDF ingestion cleanup failed",
                extra={"job_id": operation_id},
            )
            fallback_mark_failed()
        raise AppError(
            code="pdf_webhook_failed",
            message="The PDF processing result could not be applied",
            status_code=500,
        ) from exc
    finally:
        lock.release()
        await release_concurrency_by_id(
            user_id=user_id,
            category="background",
            operation_id=operation_id,
        )
