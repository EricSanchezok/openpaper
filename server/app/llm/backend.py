from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Sequence, Union, cast

import openai
from app.database.models import Message
from app.llm.token_credits import settle_token_usage
from app.schemas.responses import (
    FileContent,
    SupplementaryContent,
    TextContent,
    ToolCall,
    ToolCallResult,
)
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

logger = logging.getLogger(__name__)


class LLMResponse:
    def __init__(
        self,
        text: str,
        model: str,
        provider: str = "deepseek",
        thinking: Optional[str] = None,
        tool_calls: Optional[List[ToolCall]] = None,
    ):
        self.text = text
        self.model = model
        self.provider = provider
        self.thinking = thinking
        self.tool_calls = tool_calls or []


class StreamChunk:
    def __init__(
        self,
        text: str,
        model: str,
        provider: str = "deepseek",
        is_done: bool = False,
        thinking: str | None = None,
    ):
        self.text = text
        self.model = model
        self.provider = provider
        self.is_done = is_done
        self.thinking = thinking


MessageContent = Union[TextContent, FileContent, SupplementaryContent]
MessageParam = Union[str, Sequence[MessageContent]]


class LLMBackend(ABC):
    @property
    @abstractmethod
    def client(self) -> Any: ...

    @abstractmethod
    def generate_content(
        self,
        model: str,
        contents: Union[str, MessageParam],
        system_prompt: Optional[str] = None,
        history: Optional[List[Message]] = None,
        function_declarations: Optional[List[Dict[str, Any]]] = None,
        tool_call_results: Optional[List[ToolCallResult]] = None,
        schema: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResponse: ...

    @abstractmethod
    def send_message_stream(
        self,
        model: str,
        message: MessageParam,
        history: List[Message],
        system_prompt: str,
        file: FileContent | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]: ...

    @abstractmethod
    def get_default_model(self) -> str: ...

    @abstractmethod
    def get_fast_model(self) -> str: ...


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
        self._default_model = os.getenv(
            "DEEPSEEK_STANDARD_MODEL", "deepseek-v4-flash"
        )
        self._deep_model = os.getenv("DEEPSEEK_DEEP_MODEL", "deepseek-v4-pro")
        self._max_output_tokens = int(
            os.getenv("DEEPSEEK_MAX_OUTPUT_TOKENS", "8192")
        )

    @property
    def client(self) -> openai.OpenAI:
        return self._client

    def _reasoning_level(self, model: str) -> str:
        return "deep" if model == self._deep_model else "standard"

    def _thinking_body(self, model: str) -> dict[str, Any]:
        if self._reasoning_level(model) == "deep":
            return {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "max",
            }
        return {"thinking": {"type": "disabled"}}

    def _settle(self, *, model: str, response_id: str | None, usage: Any) -> None:
        if usage is None:
            logger.warning("deepseek_response_missing_usage", extra={"model": model})
            return
        settle_token_usage(
            model=model,
            reasoning_level=self._reasoning_level(model),
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

    def generate_content(
        self,
        model: str,
        contents: Union[str, MessageParam],
        system_prompt: Optional[str] = None,
        history: Optional[List[Message]] = None,
        function_declarations: Optional[List[Dict[str, Any]]] = None,
        tool_call_results: Optional[List[ToolCallResult]] = None,
        schema: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
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
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            extra_body=self._thinking_body(model),
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
            response_id=getattr(response, "id", None),
            usage=response.usage,
        )
        return LLMResponse(
            text=message.content or "",
            model=model,
            thinking=thinking if isinstance(thinking, str) else None,
            tool_calls=tool_calls,
        )

    def send_message_stream(
        self,
        model: str,
        message: MessageParam,
        history: List[Message],
        system_prompt: str,
        file: FileContent | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        messages = self._prepare_messages(
            history=history,
            new_message=message,
            system_prompt=system_prompt,
            file=file,
        )
        kwargs.setdefault("max_tokens", self._max_output_tokens)
        stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            extra_body=self._thinking_body(model),
            **kwargs,
        )
        response_id: str | None = None
        for chunk in stream:
            response_id = getattr(chunk, "id", response_id)
            if chunk.usage is not None:
                self._settle(
                    model=model, response_id=response_id, usage=chunk.usage
                )
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            text = choice.delta.content or ""
            thinking = getattr(choice.delta, "reasoning_content", None)
            if text or thinking or choice.finish_reason is not None:
                yield StreamChunk(
                    text=text,
                    model=model,
                    is_done=choice.finish_reason is not None,
                    thinking=thinking if isinstance(thinking, str) else None,
                )

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
        history: List[Message],
        new_message: MessageParam,
        system_prompt: str = "",
        file: FileContent | None = None,
        tool_call_results: Optional[List[ToolCallResult]] = None,
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
            messages.append(
                {"role": "assistant", "content": None, "tool_calls": calls}
            )
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
        self, declaration: Dict[str, Any]
    ) -> ChatCompletionToolParam:
        return {
            "type": "function",
            "function": {
                "name": declaration["name"],
                "description": declaration.get("description", ""),
                "parameters": declaration.get("parameters", {}),
            },
        }

    def get_default_model(self) -> str:
        return self._default_model

    def get_fast_model(self) -> str:
        return self._default_model

    def get_deep_model(self) -> str:
        return self._deep_model


__all__ = [
    "DeepSeekBackend",
    "FileContent",
    "LLMResponse",
    "LLMBackend",
    "MessageParam",
    "StreamChunk",
    "SupplementaryContent",
    "TextContent",
    "ToolCallResult",
]
