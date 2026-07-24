from __future__ import annotations

import logging
import os
import time
from typing import Any, Iterator

from app.database.models import Message, ReasoningLevel
from app.database.telemetry import track_event
from app.llm.backend import (
    FileContent,
    LLMBackend,
    LLMResponse,
    MessageParam,
    StreamChunk,
    ToolCallResult,
    get_llm_backend,
)
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


class BaseLLMClient:
    """Application-facing LLM client backed by one replaceable implementation."""

    def __init__(self) -> None:
        self.backend: LLMBackend = get_llm_backend()

    def generate_content(
        self,
        contents: MessageParam,
        system_prompt: str | None = None,
        history: list[Message] | None = None,
        function_declarations: list[dict[str, Any]] | None = None,
        tool_call_results: list[ToolCallResult] | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        schema: dict[str, Any] | None = None,
        response_model: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        start_time = time.time()
        structured_retries = (
            int(os.getenv("DEEPSEEK_STRUCTURED_RETRIES", "2"))
            if response_model is not None
            else 0
        )
        try:
            if response_model is not None:
                schema = response_model.model_json_schema()
            for attempt in range(structured_retries + 1):
                response = self.backend.generate_content(
                    contents,
                    reasoning_level=reasoning_level,
                    system_prompt=system_prompt,
                    function_declarations=function_declarations,
                    tool_call_results=tool_call_results,
                    history=history,
                    schema=schema,
                    **kwargs,
                )
                if response_model is None:
                    break
                try:
                    validated = response_model.model_validate_json(response.text)
                    response.text = validated.model_dump_json()
                    break
                except ValidationError:
                    if attempt >= structured_retries:
                        raise
                    logger.warning(
                        "Structured LLM response failed validation; retrying (%s/%s)",
                        attempt + 1,
                        structured_retries,
                    )
                    time.sleep(2**attempt)

            duration_ms = (time.time() - start_time) * 1000
            track_event(
                "llm_generate_content",
                {
                    "reasoning_level": reasoning_level.value,
                    "duration_ms": duration_ms,
                    "has_function_declarations": function_declarations is not None,
                },
            )
            logger.info("Generated LLM content in %.2fms", duration_ms)
            return response
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            track_event(
                "llm_generate_content_error",
                {
                    "reasoning_level": reasoning_level.value,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                },
            )
            logger.exception("DeepSeek generation failed")
            raise

    def send_message_stream(
        self,
        message: MessageParam,
        history: list[Message],
        system_prompt: str,
        file: FileContent | None = None,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        return self.backend.send_message_stream(
            message,
            history,
            system_prompt,
            reasoning_level=reasoning_level,
            file=file,
            **kwargs,
        )


__all__ = [
    "BaseLLMClient",
    "FileContent",
    "ReasoningLevel",
    "StreamChunk",
]
