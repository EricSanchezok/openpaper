from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from app.database.database import get_db
from sqlalchemy.orm import Session


def test_request_session_commits_once_after_success() -> None:
    session = MagicMock(spec=Session)
    with patch("app.database.database.SessionLocal", return_value=session):
        dependency = get_db()
        assert next(dependency) is session
        with pytest.raises(StopIteration):
            next(dependency)

    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()


def test_request_session_rolls_back_after_failure() -> None:
    session = MagicMock(spec=Session)
    with patch("app.database.database.SessionLocal", return_value=session):
        dependency = get_db()
        assert next(dependency) is session
        with pytest.raises(RuntimeError, match="boom"):
            dependency.throw(RuntimeError("boom"))

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
