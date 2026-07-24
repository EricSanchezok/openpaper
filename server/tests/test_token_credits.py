from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.llm.token_credits import llm_usage_context, settle_token_usage


def _settle() -> bool:
    return settle_token_usage(
        model="standard-model",
        reasoning_level="standard",
        prompt_tokens=100,
        completion_tokens=80,
        reasoning_tokens=50,
        total_tokens=180,
        provider_request_id="request-1",
        idempotency_key="job-1:metadata",
    )


def test_token_settlement_inserts_event_and_atomically_upserts_weekly_total() -> None:
    db = MagicMock()
    inserted_result = MagicMock()
    inserted_result.scalar_one_or_none.return_value = uuid.uuid4()
    db.execute.side_effect = [inserted_result, MagicMock()]

    with (
        patch("app.llm.token_credits.SessionLocal", return_value=db),
        llm_usage_context(user_id=42, feature="metadata", operation_id="job-1"),
    ):
        assert _settle() is True

    assert db.execute.call_count == 2
    weekly_statement = db.execute.call_args_list[1].args[0]
    sql = str(
        weekly_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )
    assert "ON CONFLICT (user_id, week_start) DO UPDATE" in sql
    assert "used_tokens = (" in sql
    db.commit.assert_called_once()


def test_token_settlement_is_idempotent_when_event_key_already_exists() -> None:
    db = MagicMock()
    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = None
    db.execute.return_value = duplicate_result

    with (
        patch("app.llm.token_credits.SessionLocal", return_value=db),
        llm_usage_context(user_id=42, feature="metadata", operation_id="job-1"),
    ):
        assert _settle() is False

    assert db.execute.call_count == 1
    db.rollback.assert_called_once()
    db.commit.assert_not_called()
