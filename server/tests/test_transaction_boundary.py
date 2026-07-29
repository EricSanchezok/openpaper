from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.shared.infrastructure import SqlAlchemyApplicationExecutor
from sqlalchemy.orm import Session


def _executor(
    session: MagicMock,
) -> SqlAlchemyApplicationExecutor[Session]:
    return SqlAlchemyApplicationExecutor(
        MagicMock(return_value=session),
        lambda active_session: active_session,
    )


def test_command_commits_exactly_once_after_success() -> None:
    session = MagicMock(spec=Session)

    result = _executor(session).command(lambda active_session: active_session)

    assert result is session
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()


def test_query_never_commits_and_releases_its_transaction() -> None:
    session = MagicMock(spec=Session)

    result = _executor(session).query(lambda active_session: active_session)

    assert result is session
    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_command_rolls_back_after_failure() -> None:
    session = MagicMock(spec=Session)

    with pytest.raises(RuntimeError, match="boom"):
        _executor(session).command(
            lambda _active_session: (_ for _ in ()).throw(RuntimeError("boom"))
        )

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_nested_application_operation_is_rejected() -> None:
    session = MagicMock(spec=Session)
    executor = _executor(session)

    with pytest.raises(RuntimeError, match="nested_application_operation"):
        executor.command(lambda _active_session: executor.query(lambda inner: inner))

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_async_command_commits_after_the_operation_completes() -> None:
    session = MagicMock(spec=Session)

    async def operation(active_session: Session) -> Session:
        return active_session

    result = await _executor(session).command_async(operation)

    assert result is session
    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()
