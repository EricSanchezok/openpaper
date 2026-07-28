"""Validated contracts consumed from the Jobs service."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.database.models.base import JsonValue
from app.schemas.responses import PaperMetadataExtraction
from app.schemas.responses import DataTableRow
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JobClaimResponse(BaseModel):
    claimed: bool


class JobCallbackIdentity(BaseModel):
    task_id: UUID


class StorageDeleteCallback(JobCallbackIdentity):
    deleted_count: int


class TokenUsageEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=160)
    operation_id: str = Field(min_length=1, max_length=128)
    feature: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    reasoning_level: str = Field(pattern="^(standard|deep)$")
    provider_request_id: str | None = Field(default=None, max_length=160)
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
    raw_content: str | None = None
    page_offset_map: dict[int, list[int]] | None = None
    metadata: PaperMetadataExtraction | None = None
    s3_object_key: str | None = None
    preview_s3_key: str | None = None
    parser_markdown_s3_key: str | None = None
    parser_archive_s3_key: str | None = None
    parser_backend: Literal["mineru", "pymupdf"] | None = None
    parser_quality: Literal["full", "text_only"] | None = None
    parser_version: str | None = None
    parser_warning_code: str | None = None
    parser_upgrade_pending: bool = False
    error: str | None = None
    duration: float | None = None

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
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)


class PDFParserUpgradeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    raw_content: str = Field(min_length=1)
    page_offset_map: dict[int, list[int]]
    parser_markdown_s3_key: str = Field(min_length=1)
    parser_archive_s3_key: str = Field(min_length=1)
    parser_backend: Literal["mineru"] = "mineru"
    parser_quality: Literal["full"] = "full"
    parser_version: str = Field(min_length=1)
    parser_warning_code: None = None

    @model_validator(mode="after")
    def validate_upgrade(self) -> "PDFParserUpgradeResult":
        if not self.page_offset_map:
            raise ValueError("PDF parser upgrade requires page offsets")
        return self


class PdfParserUpgradeWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    result: PDFParserUpgradeResult


class JobResponse(BaseModel):
    id: UUID
    operation: str
    document_id: UUID | None
    project_id: UUID | None
    status: str
    progress_message: str | None
    error_code: str | None
    result: dict[str, JsonValue] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class CreateAudioOverviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    additional_instructions: str | None = Field(default=None, max_length=10_000)
    length: Literal["short", "medium", "long"] = "medium"


class CreateJobResponse(BaseModel):
    job: JobResponse


class CreateDataTableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=240)
    columns: list[str] = Field(min_length=1, max_length=50)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, columns: list[str]) -> list[str]:
        normalized = [column.strip() for column in columns]
        if any(not column or len(column) > 200 for column in normalized):
            raise ValueError("columns must contain between 1 and 200 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("columns must be unique")
        return normalized


class JobListResponse(BaseModel):
    items: list[JobResponse]


class AudioSourceDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    canonical_s3_key: str


class AudioOverviewTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    scope_type: Literal["document", "project"]
    scope_id: UUID
    documents: list[AudioSourceDocumentPayload] = Field(min_length=1, max_length=100)
    length: Literal["short", "medium", "long"]
    additional_instructions: str | None = Field(default=None, max_length=10_000)


class AudioOverviewResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    title: str
    transcript: str = Field(min_length=1)
    citations: list[dict[str, object]]
    s3_object_key: str = Field(min_length=1, max_length=1024)
    voice_id: str = Field(min_length=1, max_length=160)
    model_version: str = Field(min_length=1, max_length=160)


class AudioOverviewWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: Literal["completed", "failed"]
    result: AudioOverviewResultPayload | None = None
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "AudioOverviewWebhookData":
        if self.status == "completed" and self.result is None:
            raise ValueError("completed audio job requires a result")
        if self.status == "failed" and not self.error:
            raise ValueError("failed audio job requires an error code")
        return self


class DataTableSourceDocumentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    raw_content: str


class DataTableTaskTablePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=1, max_length=50)
    papers: list[DataTableSourceDocumentPayload] = Field(min_length=1, max_length=500)


class DataTableTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    title: str | None = Field(default=None, max_length=240)
    table: DataTableTaskTablePayload


class ResearchDataTableResultPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_item_id: UUID
    title: str | None = Field(default=None, max_length=240)
    columns: list[str]
    rows: list[DataTableRow]
    row_failures: list[UUID]


class DataTableWebhookData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    status: Literal["completed", "failed"]
    result: ResearchDataTableResultPayload | None = None
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_state(self) -> "DataTableWebhookData":
        if self.status == "completed" and self.result is None:
            raise ValueError("completed data-table job requires a result")
        if self.status == "failed" and not self.error:
            raise ValueError("failed data-table job requires an error code")
        return self
