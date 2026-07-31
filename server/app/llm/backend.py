from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Generic, Iterator, Protocol, Sequence, TypeVar, cast

import openai
from app.database.models import ReasoningLevel
from app.llm.token_credits import settle_token_usage
from app.modules.papers.application.contracts.extraction import (
    FileContent,
    SupplementaryContent,
    TextContent,
    ToolCall,
    ToolCallResult,
)
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

logger = logging.getLogger(__name__)
T = TypeVar("T")
_DEEPSEEK_MAX_OUTPUT_TOKENS = 384 * 1024


class LLMUsageSettlementError(RuntimeError):
    """Provider usage was received but could not be durably recorded."""


class _StreamCancellation:
    """Thread-safe cancellation of the provider response, not its generator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._close_provider: Callable[[], None] | None = None

    def attach(self, close_provider: Callable[[], None]) -> None:
        with self._lock:
            self._close_provider = close_provider
            cancelled = self._cancelled
        if cancelled:
            close_provider()

    def detach(self) -> None:
        with self._lock:
            self._close_provider = None

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            close_provider = self._close_provider
        if close_provider is not None:
            close_provider()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled


class _CancellableIterator(Iterator[T], Generic[T]):
    """Keep generator ownership in its reader thread while exposing safe I/O cancel."""

    def __init__(
        self,
        factory: Callable[[_StreamCancellation], Iterator[T]],
    ) -> None:
        self._cancellation = _StreamCancellation()
        self._iterator = factory(self._cancellation)

    def __iter__(self) -> _CancellableIterator[T]:
        return self

    def __next__(self) -> T:
        if self._cancellation.cancelled:
            raise StopIteration
        return next(self._iterator)

    def cancel(self) -> None:
        self._cancellation.cancel()

    def close(self) -> None:
        self._cancellation.cancel()
        close_iterator = getattr(self._iterator, "close", None)
        if callable(close_iterator):
            close_iterator()


@dataclass(slots=True)
class LLMResponse:
    text: str
    thinking: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class StreamChunk:
    text: str
    is_done: bool = False
    thinking: str | None = None


MessageContent = TextContent | FileContent | SupplementaryContent
MessageParam = str | Sequence[MessageContent]


class HistoryMessage(Protocol):
    @property
    def role(self) -> str: ...

    @property
    def content(self) -> str: ...


class LLMBackend(ABC):
    @abstractmethod
    def model_revision(
        self,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> str: ...

    @abstractmethod
    def generate_content(
        self,
        contents: MessageParam,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        system_prompt: str | None = None,
        history: Sequence[HistoryMessage] | None = None,
        function_declarations: list[dict[str, Any]] | None = None,
        tool_call_results: list[ToolCallResult] | None = None,
        schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse: ...

    @abstractmethod
    def send_message_stream(
        self,
        message: MessageParam,
        history: Sequence[HistoryMessage],
        system_prompt: str,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        file: FileContent | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]: ...


def _usage_value(usage: Any, name: str) -> int:
    value = getattr(usage, name, 0) if usage is not None else 0
    return int(value or 0)


def _completion_detail(usage: Any, name: str) -> int:
    details = getattr(usage, "completion_tokens_details", None)
    return _usage_value(details, name)


class DeepSeekBackend(LLMBackend):
    """DeepSeek-only implementation over its documented OpenAI-compatible API."""

    def __init__(self) -> None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is required")
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=float(os.getenv("DEEPSEEK_REQUEST_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "2")),
        )
        self._default_model = os.getenv("DEEPSEEK_STANDARD_MODEL", "deepseek-v4-flash")
        self._deep_model = os.getenv("DEEPSEEK_DEEP_MODEL", "deepseek-v4-pro")
        self._max_output_tokens = int(
            os.getenv(
                "DEEPSEEK_MAX_OUTPUT_TOKENS",
                str(_DEEPSEEK_MAX_OUTPUT_TOKENS),
            )
        )

    def _model(self, reasoning_level: ReasoningLevel) -> str:
        if reasoning_level == ReasoningLevel.DEEP:
            return self._deep_model
        return self._default_model

    def model_revision(
        self,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> str:
        return f"deepseek:{self._model(reasoning_level)}"

    def _thinking_body(self, reasoning_level: ReasoningLevel) -> dict[str, Any]:
        if reasoning_level == ReasoningLevel.DEEP:
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "max",
            }
        return {"thinking": {"type": "disabled"}}

    def _settle(
        self,
        *,
        model: str,
        reasoning_level: ReasoningLevel,
        response_id: str | None,
        usage: Any,
    ) -> None:
        try:
            if usage is None:
                logger.warning("deepseek_response_missing_usage", extra={"model": model})
                settle_token_usage(
                    model=model,
                    reasoning_level=reasoning_level.value,
                    provider_request_id=response_id,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    idempotency_key=(
                        f"deepseek:{response_id}" if response_id else None
                    ),
                    status="unknown",
                )
                return
            settle_token_usage(
                model=model,
                reasoning_level=reasoning_level.value,
                provider_request_id=response_id,
                prompt_tokens=_usage_value(usage, "prompt_tokens"),
                completion_tokens=_usage_value(usage, "completion_tokens"),
                reasoning_tokens=_completion_detail(usage, "reasoning_tokens"),
                cache_hit_tokens=_usage_value(usage, "prompt_cache_hit_tokens"),
                cache_miss_tokens=_usage_value(usage, "prompt_cache_miss_tokens"),
                total_tokens=_usage_value(usage, "total_tokens"),
                idempotency_key=(
                    f"deepseek:{response_id}" if response_id else None
                ),
            )
        except Exception as exc:
            raise LLMUsageSettlementError(
                "LLM token usage could not be settled"
            ) from exc

    def generate_content(
        self,
        contents: MessageParam,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        system_prompt: str | None = None,
        history: Sequence[HistoryMessage] | None = None,
        function_declarations: list[dict[str, Any]] | None = None,
        tool_call_results: list[ToolCallResult] | None = None,
        schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        model = self._model(reasoning_level)
        prompt = system_prompt or ""
        if schema:
            prompt = (
                f"{prompt}\n\nReturn one valid JSON object matching this schema exactly:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
            kwargs["response_format"] = {"type": "json_object"}

        messages = self._prepare_messages(
            history=history or [],
            new_message=contents,
            system_prompt=prompt,
            tool_call_results=tool_call_results,
        )
        if function_declarations:
            kwargs["tools"] = [
                self._cast_tool_declaration(item) for item in function_declarations
            ]
        kwargs.setdefault("max_tokens", self._max_output_tokens)
        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            extra_body=self._thinking_body(reasoning_level),
            **kwargs,
        )
        if not response.choices:
            raise ValueError("DeepSeek returned no choices")
        message = response.choices[0].message
        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    args=json.loads(call.function.arguments or "{}"),
                )
            )
        thinking = getattr(message, "reasoning_content", None)
        self._settle(
            model=model,
            reasoning_level=reasoning_level,
            response_id=getattr(response, "id", None),
            usage=response.usage,
        )
        return LLMResponse(
            text=message.content or "",
            thinking=thinking if isinstance(thinking, str) else None,
            tool_calls=tool_calls,
        )

    def send_message_stream(
        self,
        message: MessageParam,
        history: Sequence[HistoryMessage],
        system_prompt: str,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        file: FileContent | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        model = self._model(reasoning_level)
        messages = self._prepare_messages(
            history=history,
            new_message=message,
            system_prompt=system_prompt,
            file=file,
        )
        kwargs.setdefault("max_tokens", self._max_output_tokens)

        def stream_chunks(
            cancellation: _StreamCancellation,
        ) -> Iterator[StreamChunk]:
            stream = self._client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                stream_options={"include_usage": True},
                extra_body=self._thinking_body(reasoning_level),
                **kwargs,
            )
            close_provider = getattr(stream, "close", None)
            if callable(close_provider):
                cancellation.attach(close_provider)
            response_id: str | None = None
            usage_received = False
            stream_failed = False
            try:
                if cancellation.cancelled:
                    return
                for chunk in stream:
                    response_id = getattr(chunk, "id", response_id)
                    if chunk.usage is not None:
                        usage_received = True
                        self._settle(
                            model=model,
                            reasoning_level=reasoning_level,
                            response_id=response_id,
                            usage=chunk.usage,
                        )
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    text = choice.delta.content or ""
                    thinking = getattr(choice.delta, "reasoning_content", None)
                    if text or thinking or choice.finish_reason is not None:
                        yield StreamChunk(
                            text=text,
                            is_done=choice.finish_reason is not None,
                            thinking=(
                                thinking if isinstance(thinking, str) else None
                            ),
                        )
            except BaseException:
                stream_failed = True
                raise
            finally:
                cancellation.detach()
                if not usage_received:
                    try:
                        self._settle(
                            model=model,
                            reasoning_level=reasoning_level,
                            response_id=response_id,
                            usage=None,
                        )
                    except LLMUsageSettlementError:
                        if not stream_failed:
                            raise
                        logger.exception(
                            "Token usage settlement failed after provider stream error"
                        )

        return _CancellableIterator(stream_chunks)

    def _convert_message_content(self, content: MessageParam) -> Any:
        if isinstance(content, str):
            return content
        parts: list[dict[str, str]] = []
        for item in content:
            if isinstance(item, TextContent):
                parts.append({"type": "text", "text": item.text})
            elif isinstance(item, SupplementaryContent):
                parts.append(
                    {
                        "type": "text",
                        "text": f"<{item.label}>\n{item.content}\n</{item.label}>",
                    }
                )
            elif isinstance(item, FileContent):
                if item.text_fallback is None:
                    raise ValueError(
                        "FileContent.text_fallback is required for DeepSeek"
                    )
                filename = item.filename or "document.pdf"
                parts.append(
                    {
                        "type": "text",
                        "text": (
                            f'<document filename="{filename}">\n'
                            f"{item.text_fallback}\n</document>"
                        ),
                    }
                )
        return parts

    def _prepare_messages(
        self,
        history: Sequence[HistoryMessage],
        new_message: MessageParam,
        system_prompt: str = "",
        file: FileContent | None = None,
        tool_call_results: list[ToolCallResult] | None = None,
    ) -> list[ChatCompletionMessageParam]:
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if file:
            messages.append(
                {"role": "user", "content": self._convert_message_content([file])}
            )
        for item in history:
            role = "assistant" if item.role == "assistant" else "user"
            messages.append({"role": role, "content": str(item.content)})
        if tool_call_results:
            calls = []
            for index, result in enumerate(tool_call_results):
                calls.append(
                    {
                        "id": result.id or f"call_{index}",
                        "type": "function",
                        "function": {
                            "name": result.name,
                            "arguments": json.dumps(result.args),
                        },
                    }
                )
            messages.append({"role": "assistant", "content": None, "tool_calls": calls})
            for index, result in enumerate(tool_call_results):
                value = result.result
                content = (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.id or f"call_{index}",
                        "content": content,
                    }
                )
        messages.append(
            {"role": "user", "content": self._convert_message_content(new_message)}
        )
        return cast(list[ChatCompletionMessageParam], messages)

    def _cast_tool_declaration(
        self, declaration: dict[str, Any]
    ) -> ChatCompletionToolParam:
        return {
            "type": "function",
            "function": {
                "name": declaration["name"],
                "description": declaration.get("description", ""),
                "parameters": declaration.get("parameters", {}),
            },
        }


@lru_cache(maxsize=1)
def get_llm_backend() -> LLMBackend:
    """Return the process-wide backend and its reusable HTTP connection pool."""
    return DeepSeekBackend()


__all__ = [
    "DeepSeekBackend",
    "FileContent",
    "LLMResponse",
    "LLMBackend",
    "LLMUsageSettlementError",
    "MessageParam",
    "StreamChunk",
    "SupplementaryContent",
    "TextContent",
    "ToolCallResult",
    "get_llm_backend",
]
