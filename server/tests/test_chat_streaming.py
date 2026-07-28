"""Post-header chat failures use one stable public event."""

from unittest.mock import MagicMock

import pytest
from app.services.chat_streaming import stream_with_stable_error
from sqlalchemy.orm import Session


@pytest.mark.asyncio
async def test_stream_failure_is_redacted_and_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_stream():
        yield "first"
        raise RuntimeError("provider secret")

    track_event = MagicMock()
    monkeypatch.setattr(
        "app.services.chat_streaming.track_event",
        track_event,
    )

    events = [
        event
        async for event in stream_with_stable_error(
            failing_stream(),
            delimiter="END",
            event_name="chat_error",
            user_id=7,
            db=MagicMock(spec=Session),
            properties={"conversation_id": "conversation"},
        )
    ]

    assert events == [
        "first",
        '{"type": "error", "content": "chat_failed"}END',
    ]
    assert "provider secret" not in events[-1]
    assert track_event.call_args.kwargs["properties"]["error_type"] == "RuntimeError"
