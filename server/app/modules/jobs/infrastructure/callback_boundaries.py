"""Savepoint boundary for optional callback projections."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

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
            "jobs.callback.optional_side_effect_failed",
            extra={"operation": operation, **context},
        )


__all__ = ["optional_savepoint"]
