"""Post-header chat failures use one stable public event."""

import json
from unittest.mock import MagicMock

import pytest
from app.modules.conversations.infrastructure.chat_streaming import (
    encode_conversation_sse,
    stream_with_stable_error,
)
from app.modules.conversations.application.contracts.messages import (
    ConversationStreamCompleteEvent,
    ConversationStreamContentDeltaEvent,
)


def _payload(event: str) -> dict[str, object]:
    data = next(
        line.removeprefix("data: ")
        for line in event.splitlines()
        if line.startswith("data: ")
    )
    value = json.loads(data)
    assert isinstance(value, dict)
    return value


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
            event_name="chat_error",
            user_id=7,
            properties={"conversation_id": "conversation"},
            diagnostic_recorder=recorder,
        )
    ]

    assert events[0] == "first"
    failure = _payload(events[-1])
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
        yield encode_conversation_sse(
            ConversationStreamContentDeltaEvent(delta="partial")
        )

    monkeypatch.setattr(
        "app.modules.conversations.infrastructure.chat_streaming.track_event",
        MagicMock(),
    )
    events = [
        event
        async for event in stream_with_stable_error(
            incomplete_stream(),
            event_name="chat_error",
            user_id=7,
            properties={},
        )
    ]
    failure = _payload(events[-1])
    assert failure["error"]["code"] == "stream_incomplete"


@pytest.mark.asyncio
async def test_complete_stream_has_no_error_event() -> None:
    async def completed_stream():
        yield encode_conversation_sse(
            ConversationStreamContentDeltaEvent(delta="answer")
        )
        yield encode_conversation_sse(
            ConversationStreamCompleteEvent(
                turn_id="00000000-0000-0000-0000-000000000001"
            )
        )

    events = [
        event
        async for event in stream_with_stable_error(
            completed_stream(),
            event_name="chat_error",
            user_id=7,
            properties={},
        )
    ]
    assert _payload(events[-1])["type"] == "complete"
