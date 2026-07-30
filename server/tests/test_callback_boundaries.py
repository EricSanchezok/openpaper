"""Optional callback projections are isolated by a savepoint."""

from unittest.mock import MagicMock

from app.modules.jobs.infrastructure.callback_boundaries import (
    optional_savepoint,
)
from sqlalchemy.orm import Session


def test_optional_savepoint_contains_failure() -> None:
    db = MagicMock(spec=Session)
    savepoint = MagicMock()
    db.begin_nested.return_value = savepoint

    with optional_savepoint(db, operation="optional", context={}):
        raise RuntimeError("optional failure")

    savepoint.__exit__.assert_called_once()
