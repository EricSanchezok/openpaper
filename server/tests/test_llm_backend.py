from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.api.message_api import ChatMessageRequest, MultiPaperChatRequest
from app.database.models import ReasoningLevel
from app.llm.base import BaseLLMClient
from app.llm.backend import DeepSeekBackend
from app.llm.backend import LLMResponse
from app.llm.token_credits import utc_week_start
from pydantic import BaseModel


def _backend(monkeypatch: pytest.MonkeyPatch) -> DeepSeekBackend:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_STANDARD_MODEL", "standard-model")
    monkeypatch.setenv("DEEPSEEK_DEEP_MODEL", "deep-model")
    with patch("app.llm.backend.openai.OpenAI"):
        return DeepSeekBackend()


def test_deepseek_routes_only_standard_and_deep_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(monkeypatch)

    assert backend._model(ReasoningLevel.STANDARD) == "standard-model"
    assert backend._model(ReasoningLevel.DEEP) == "deep-model"
    assert backend._thinking_body(ReasoningLevel.STANDARD) == {
        "thinking": {"type": "disabled"}
    }
    assert backend._thinking_body(ReasoningLevel.DEEP) == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }


def test_provider_settles_total_tokens_without_double_counting_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(monkeypatch)
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=80,
        total_tokens=180,
        prompt_cache_hit_tokens=40,
        prompt_cache_miss_tokens=60,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=50),
    )

    with patch("app.llm.backend.settle_token_usage") as settle:
        backend._settle(
            model="deep-model",
            reasoning_level=ReasoningLevel.DEEP,
            response_id="request-1",
            usage=usage,
        )

    settle.assert_called_once_with(
        model="deep-model",
        reasoning_level="deep",
        provider_request_id="request-1",
        prompt_tokens=100,
        completion_tokens=80,
        reasoning_tokens=50,
        cache_hit_tokens=40,
        cache_miss_tokens=60,
        total_tokens=180,
        idempotency_key="deepseek:request-1",
    )


def test_stream_replays_reasoning_and_settles_final_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(monkeypatch)
    backend._client.chat.completions.create.return_value = iter(
        [
            SimpleNamespace(
                id="request-2",
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content=None, reasoning_content="checking evidence"
                        ),
                        finish_reason=None,
                    )
                ],
            ),
            SimpleNamespace(
                id="request-2",
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                    completion_tokens_details=None,
                ),
                choices=[],
            ),
        ]
    )

    with patch.object(backend, "_settle") as settle:
        chunks = list(
            backend.send_message_stream(
                "question",
                [],
                "system",
                reasoning_level=ReasoningLevel.DEEP,
            )
        )

    assert chunks[0].thinking == "checking evidence"
    settle.assert_called_once()


def test_stream_records_unknown_usage_when_final_usage_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend(monkeypatch)
    backend._client.chat.completions.create.return_value = iter(
        [
            SimpleNamespace(
                id="request-3",
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="answer", reasoning_content=None),
                        finish_reason="stop",
                    )
                ],
            )
        ]
    )

    with patch.object(backend, "_settle") as settle:
        list(backend.send_message_stream("question", [], "system"))

    settle.assert_called_once_with(
        model="standard-model",
        reasoning_level=ReasoningLevel.STANDARD,
        response_id="request-3",
        usage=None,
    )


def test_chat_requests_reject_legacy_provider_fields() -> None:
    base = {
        "paper_id": "00000000-0000-0000-0000-000000000001",
        "conversation_id": "00000000-0000-0000-0000-000000000002",
        "user_query": "Explain the result",
    }
    with pytest.raises(ValidationError):
        ChatMessageRequest.model_validate({**base, "llm_provider": "gemini"})
    with pytest.raises(ValidationError):
        MultiPaperChatRequest.model_validate(
            {
                "conversation_id": base["conversation_id"],
                "user_query": base["user_query"],
                "reasoning_level": "extreme",
            }
        )


def test_token_week_starts_monday_utc() -> None:
    assert utc_week_start(datetime(2026, 7, 26, 23, 59, tzinfo=UTC)).isoformat() == (
        "2026-07-20"
    )
    assert utc_week_start(datetime(2026, 7, 27, 0, 0, tzinfo=UTC)).isoformat() == (
        "2026-07-27"
    )


def test_structured_response_is_pydantic_validated_and_retried() -> None:
    class Result(BaseModel):
        answer: str

    backend = MagicMock()
    backend.generate_content.side_effect = [
        LLMResponse(text='{"wrong":"shape"}'),
        LLMResponse(text='{"answer":"grounded"}'),
    ]
    client = BaseLLMClient.__new__(BaseLLMClient)
    client.backend = backend

    with patch("app.llm.base.time.sleep"):
        response = client.generate_content("question", response_model=Result)

    assert response.text == '{"answer":"grounded"}'
    assert backend.generate_content.call_count == 2
