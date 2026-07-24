"""Validated contracts consumed from the Jobs service."""

from __future__ import annotations

from typing import Literal, Optional

from app.schemas.responses import PaperMetadataExtraction
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TokenUsageEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=128)
    feature: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    reasoning_level: str = Field(pattern="^(standard|deep)$")
    provider_request_id: Optional[str] = Field(default=None, max_length=160)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cache_hit_tokens: int = Field(default=0, ge=0)
    cache_miss_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(ge=0)
    status: str = Field(default="settled", pattern="^(settled|unknown)$")


class PDFProcessingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    job_id: str
    raw_content: Optional[str] = None
    page_offset_map: Optional[dict[int, list[int]]] = None
    metadata: Optional[PaperMetadataExtraction] = None
    s3_object_key: Optional[str] = None
    file_url: Optional[str] = None
    preview_url: Optional[str] = None
    preview_object_key: Optional[str] = None
    parser_markdown_s3_key: Optional[str] = None
    parser_archive_s3_key: Optional[str] = None
    parser_backend: Optional[Literal["mineru", "pymupdf"]] = None
    parser_quality: Optional[Literal["full", "text_only"]] = None
    parser_version: Optional[str] = None
    parser_warning_code: Optional[str] = None
    error: Optional[str] = None
    duration: Optional[float] = None

    @model_validator(mode="after")
    def validate_result_state(self) -> "PDFProcessingResult":
        if self.success:
            if (
                not self.raw_content
                or not self.page_offset_map
                or self.parser_backend is None
                or self.parser_quality is None
                or not self.parser_version
            ):
                raise ValueError("successful PDF result is incomplete")
        elif not self.error:
            raise ValueError("failed PDF result requires an error code")
        return self


class PdfProcessingWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: Literal["completed", "failed"]
    result: PDFProcessingResult
    error: Optional[str] = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)
