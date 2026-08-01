"""Post-header chat failures use one stable public event."""

import json
from unittest.mock import MagicMock

import pytest
from app.modules.conversations.infrastructure.chat_streaming import (
    stream_with_stable_error,
)


@pytest.mark.asyncio
async def test_stream_failure_is_redacted_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_stream():
        yield "first"
        raise RuntimeError("provider secret")

    track_event = MagicMock()
    recorder = MagicMock()
    monkeypatch.setattr(
        "app.modules.conversations.infrastructure.chat_streaming.track_event",
        track_event,
    )

    events = [
        event
        async for event in stream_with_stable_error(
            failing_stream(),
            delimiter="END",
            event_name="chat_error",
            user_id=7,
            properties={"conversation_id": "conversation"},
            diagnostic_recorder=recorder,
        )
    ]

    assert events[0] == "first"
    failure = json.loads(events[-1].removesuffix("END"))
    assert failure["type"] == "error"
    assert failure["error"]["code"] == "chat_stream_failed"
    assert failure["error"]["kind"] == "dependency_failure"
    assert failure["error"]["retryable"] is True
    assert "provider secret" not in events[-1]
    assert track_event.call_args.kwargs["properties"]["error_type"] == "RuntimeError"
    snapshot = recorder.record.call_args.args[0]
    assert str(snapshot.id) == failure["error"]["diagnostic_id"]
    assert snapshot.sections["failure"]["code"] == "chat_stream_failed"


@pytest.mark.asyncio
async def test_stream_requires_explicit_complete_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def incomplete_stream():
        yield '{"type":"content","content":"partial"}END'

    monkeypatch.setattr(
        "app.modules.conversations.infrastructure.chat_streaming.track_event",
        MagicMock(),
    )
    events = [
        event
        async for event in stream_with_stable_error(
            incomplete_stream(),
            delimiter="END",
            event_name="chat_error",
            user_id=7,
            properties={},
        )
    ]
    failure = json.loads(events[-1].removesuffix("END"))
    assert failure["error"]["code"] == "stream_incomplete"


@pytest.mark.asyncio
async def test_complete_stream_has_no_error_event() -> None:
    async def completed_stream():
        yield '{"type":"content","content":"answer"}END'
        yield '{"type":"complete","content":{}}END'

    events = [
        event
        async for event in stream_with_stable_error(
            completed_stream(),
            delimiter="END",
            event_name="chat_error",
            user_id=7,
            properties={},
        )
    ]
    assert events[-1] == '{"type":"complete","content":{}}END'
