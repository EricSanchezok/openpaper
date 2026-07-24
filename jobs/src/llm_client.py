"""DeepSeek-only structured extraction client for background jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Callable, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field, create_model

from src.prompts import EXTRACT_COLS_INSTRUCTION, EXTRACT_METADATA_PROMPT_TEMPLATE
from src.schemas import DataTableCellValue, DataTableRow, PaperMetadataExtraction
from src.token_usage import record_token_usage
from src.utils import time_it

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class DeepSeekExtractionClient:
    """Small JSON-mode client shared by metadata and data-table jobs."""

    def __init__(self) -> None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY environment variable is not set")

        self.model = os.getenv("DEEPSEEK_STANDARD_MODEL", "deepseek-v4-flash")
        self.max_output_tokens = int(
            os.getenv("DEEPSEEK_MAX_OUTPUT_TOKENS", "8192")
        )
        self.max_input_chars = int(
            os.getenv("DEEPSEEK_MAX_INPUT_CHARS", "300000")
        )
        self.structured_retries = int(
            os.getenv("DEEPSEEK_STRUCTURED_RETRIES", "2")
        )
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            timeout=float(os.getenv("DEEPSEEK_REQUEST_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "2")),
        )

    async def _generate_structured(
        self,
        *,
        prompt: str,
        schema: type[T],
        feature: str,
        idempotency_suffix: str,
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        messages = [
            {
                "role": "system",
                "content": (
                    "Return exactly one JSON object matching the supplied JSON "
                    "Schema. Do not add markdown or commentary."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\nJSON Schema:\n{schema_json}"
                )[: self.max_input_chars],
            },
        ]

        last_error: Exception | None = None
        for attempt in range(self.structured_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    max_tokens=self.max_output_tokens,
                    temperature=0,
                )
                record_token_usage(
                    feature=feature,
                    model=self.model,
                    usage=response.usage,
                    request_id=response.id,
                    idempotency_suffix=f"{idempotency_suffix}:attempt:{attempt}",
                )
                content = response.choices[0].message.content or ""
                return schema.model_validate_json(content)
            except Exception as exc:
                last_error = exc
                if attempt >= self.structured_retries:
                    break
                await asyncio.sleep(2**attempt)

        raise ValueError(
            f"DeepSeek returned invalid structured output for {schema.__name__}"
        ) from last_error

    async def extract_paper_metadata(
        self,
        paper_content: str,
        job_id: str,
        status_callback: Callable[[str], None] | None = None,
    ) -> PaperMetadataExtraction:
        if status_callback:
            status_callback("Extracting paper metadata")

        prompt = (
            f"{EXTRACT_METADATA_PROMPT_TEMPLATE}\n\n"
            f"Paper content:\n{paper_content}"
        )
        async with time_it("Extracting paper metadata from DeepSeek", job_id=job_id):
            result = await self._generate_structured(
                prompt=prompt,
                schema=PaperMetadataExtraction,
                feature="paper_metadata",
                idempotency_suffix="paper_metadata",
            )

        if status_callback:
            status_callback(f"Read {result.title or 'paper'}")
        return result

    async def extract_data_table(
        self,
        *,
        columns: list[str],
        paper_content: str,
        paper_id: str,
    ) -> DataTableRow:
        aliases = {f"col_{index}": column for index, column in enumerate(columns)}
        field_definitions: dict[str, Any] = {
            alias: (
                DataTableCellValue,
                Field(description=f"Value and citations for {column!r}"),
            )
            for alias, column in aliases.items()
        }
        values_model = create_model(
            "ValuesModel",
            __config__=ConfigDict(extra="forbid"),
            **field_definitions,
        )
        cols = "\n".join(
            f'- {alias}: "{column}"' for alias, column in aliases.items()
        )
        prompt = (
            EXTRACT_COLS_INSTRUCTION.format(
                cols_str=cols,
                n_cols=len(columns),
            )
            + f"\n\nPaper content:\n{paper_content}"
        )
        values: Any = await self._generate_structured(
            prompt=prompt,
            schema=values_model,
            feature="data_table",
            idempotency_suffix=f"data_table:{paper_id}",
        )
        return DataTableRow(
            paper_id=paper_id,
            values={
                column: getattr(values, alias)
                for alias, column in aliases.items()
            },
        )


llm_client = DeepSeekExtractionClient()
