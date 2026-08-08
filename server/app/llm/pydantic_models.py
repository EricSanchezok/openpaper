"""Shared Pydantic AI model construction for Scholens-owned LLM features."""

from __future__ import annotations

import os
from typing import Any, cast

import openai
from app.shared.domain.enums import ReasoningLevel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

_DEFAULT_MAX_OUTPUT_TOKENS = 384 * 1024


def build_deepseek_chat_model(
    reasoning_level: ReasoningLevel,
    *,
    max_output_tokens: int | None = None,
) -> OpenAIChatModel:
    """Build the configured OpenAI-compatible DeepSeek chat model."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY environment variable is required")
    model_name = os.getenv(
        "DEEPSEEK_DEEP_MODEL"
        if reasoning_level is ReasoningLevel.DEEP
        else "DEEPSEEK_STANDARD_MODEL",
        "deepseek-v4-pro"
        if reasoning_level is ReasoningLevel.DEEP
        else "deepseek-v4-flash",
    )
    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        timeout=float(os.getenv("DEEPSEEK_REQUEST_TIMEOUT_SECONDS", "120")),
        max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "2")),
    )
    settings = OpenAIChatModelSettings(
        max_tokens=(
            max_output_tokens
            if max_output_tokens is not None
            else int(
                os.getenv(
                    "DEEPSEEK_MAX_OUTPUT_TOKENS",
                    str(_DEFAULT_MAX_OUTPUT_TOKENS),
                )
            )
        ),
        parallel_tool_calls=False,
        extra_body=(
            {"thinking": {"type": "enabled"}, "reasoning_effort": "max"}
            if reasoning_level is ReasoningLevel.DEEP
            else {"thinking": {"type": "disabled"}}
        ),
    )
    return OpenAIChatModel(
        cast(Any, model_name),
        provider=OpenAIProvider(openai_client=client),
        settings=settings,
    )
