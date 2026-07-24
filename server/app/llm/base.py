from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional

from app.database.models import Message, ReasoningLevel
from app.database.telemetry import track_event
from app.llm.backend import (
    DeepSeekBackend,
    FileContent,
    LLMBackend,
    LLMResponse,
    MessageParam,
    StreamChunk,
    ToolCallResult,
)
from app.llm.utils import retry_llm_operation
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ModelType(Enum):
    DEFAULT = "default"
    FAST = "fast"


class BaseLLMClient:
    """Single-provider client with an internal, replaceable model router."""

    def __init__(self) -> None:
        self.backend: LLMBackend = DeepSeekBackend()

    def _model(
        self,
        model_type: ModelType,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
    ) -> str:
        if reasoning_level == ReasoningLevel.DEEP:
            return cast_deepseek(self.backend).get_deep_model()
        if model_type == ModelType.FAST:
            return self.backend.get_fast_model()
        return self.backend.get_default_model()

    @retry_llm_operation(max_retries=3, delay=1.0)
    def generate_content(
        self,
        contents: Any,
        system_prompt: Optional[str] = None,
        history: Optional[List[Message]] = None,
        function_declarations: Optional[List[Dict[str, Any]]] = None,
        tool_call_results: Optional[List[ToolCallResult]] = None,
        model_type: ModelType = ModelType.DEFAULT,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        schema: Optional[Dict[str, Any]] = None,
        response_model: type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        start_time = time.time()
        model = self._model(model_type, reasoning_level)
        try:
            if response_model is not None:
                schema = response_model.model_json_schema()
            response = self.backend.generate_content(
                model,
                contents,
                system_prompt=system_prompt,
                function_declarations=function_declarations,
                tool_call_results=tool_call_results,
                history=history,
                schema=schema,
                **kwargs,
            )
            if response_model is not None:
                validated = response_model.model_validate_json(response.text)
                response.text = validated.model_dump_json()
            duration_ms = (time.time() - start_time) * 1000
            track_event(
                "llm_generate_content",
                {
                    "model": model,
                    "provider": "deepseek",
                    "model_type": model_type.value,
                    "reasoning_level": reasoning_level.value,
                    "duration_ms": duration_ms,
                    "has_function_declarations": function_declarations is not None,
                },
            )
            logger.info(
                "Generated content using deepseek/%s in %.2fms", model, duration_ms
            )
            return response
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            track_event(
                "llm_generate_content_error",
                {
                    "model": model,
                    "provider": "deepseek",
                    "model_type": model_type.value,
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
        history: List[Message],
        system_prompt: str,
        file: FileContent | None = None,
        model_type: ModelType = ModelType.DEFAULT,
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        model = self._model(model_type, reasoning_level)
        return self.backend.send_message_stream(
            model, message, history, system_prompt, file, **kwargs
        )

    @property
    def default_model(self) -> str:
        return self.backend.get_default_model()

    @property
    def fast_model(self) -> str:
        return self.backend.get_fast_model()


def cast_deepseek(backend: LLMBackend) -> DeepSeekBackend:
    if not isinstance(backend, DeepSeekBackend):
        raise RuntimeError("Configured LLM backend does not support deep reasoning")
    return backend


__all__ = [
    "BaseLLMClient",
    "FileContent",
    "ModelType",
    "ReasoningLevel",
    "StreamChunk",
]
