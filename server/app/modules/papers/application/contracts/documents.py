from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.shared.domain import JsonValue
from app.shared.domain.enums import DocumentProcessingStatus, PaperStatus
from app.modules.papers.application.contracts.extraction import ResponseCitation
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentUpdate(BaseModel):
    """Validated canonical metadata written by trusted ingestion workflows."""

    model_config = ConfigDict(extra="forbid")

    preview_s3_key: str | None = None
    authors: list[str] | None = None
    title: str | None = None
    abstract: str | None = None
    institutions: list[str] | None = None
    keywords: list[str] | None = None
    summary: str | None = None
    summary_citations: list[ResponseCitation] | None = None
    starter_questions: list[str] | None = None
    publish_date: datetime | str | None = None
    raw_content: str | None = None
    parser_markdown_s3_key: str | None = None
    parser_archive_s3_key: str | None = None
    parser_backend: str | None = None
    parser_quality: str | None = None
    parser_version: str | None = None
    parser_warning_code: str | None = None
    processing_status: str | None = None
    processing_job_id: UUID | None = None
    gc_after: datetime | None = None
    page_offset_map: dict[int, list[int]] | None = None
    doi: str | None = None
    journal: str | None = None
    publisher: str | None = None
    attempted_metadata_at: datetime | None = None
    field_provenance: dict[str, JsonValue] | None = None


class DocumentMetadataOverrides(BaseModel):
    """The only canonical metadata fields a Library owner may override."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=1_000)
    authors: list[str] | None = Field(default=None, max_length=100)
    abstract: str | None = Field(default=None, max_length=100_000)
    institutions: list[str] | None = Field(default=None, max_length=100)
    doi: str | None = Field(default=None, max_length=500)
    journal: str | None = Field(default=None, max_length=1_000)
    publisher: str | None = Field(default=None, max_length=1_000)
    publish_date: datetime | None = None

    @field_validator("authors", "institutions")
    @classmethod
    def validate_list_values(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 500 for value in normalized):
            raise ValueError(
                "metadata list values must be between 1 and 500 characters"
            )
        return normalized


class LibraryPaperUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PaperStatus | None = None
    metadata_overrides: DocumentMetadataOverrides | None = None


class DocumentResponse(BaseModel):
    id: UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    title: str | None
    authors: list[str] | None
    abstract: str | None
    institutions: list[str] | None
    keywords: list[str] | None
    doi: str | None
    journal: str | None
    publisher: str | None
    publish_date: datetime | None
    summary: str | None
    summary_citations: list[ResponseCitation] | None
    starter_questions: list[str] | None
    processing_status: DocumentProcessingStatus
    parser_quality: str | None
    parser_warning_code: str | None
    created_at: datetime
    updated_at: datetime


class LibraryPaperTagResponse(BaseModel):
    id: UUID
    name: str
    color: str | None


class LibraryPaperResponse(BaseModel):
    id: UUID
    user_id: int
    status: PaperStatus
    last_accessed_at: datetime
    metadata_overrides: DocumentMetadataOverrides
    is_public: bool
    preview_url: str | None
    tags: list[LibraryPaperTagResponse]
    document: DocumentResponse
    created_at: datetime
    updated_at: datetime


class LibraryPaperListResponse(BaseModel):
    items: list[LibraryPaperResponse]


class LibraryPaperShareResponse(BaseModel):
    share_token: str
    is_public: bool


class PublicPaperOwnerResponse(BaseModel):
    id: int
    display_name: str


class PublicPaperResponse(BaseModel):
    document: DocumentResponse
    file_url: str
    owner: PublicPaperOwnerResponse


class CollectPublicPaperResponse(BaseModel):
    document_id: UUID
    library_paper_id: UUID
    already_exists: bool


class DocumentFileUrlResponse(BaseModel):
    file_url: str
    expires_in_seconds: int


class DocumentContentResponse(BaseModel):
    document_id: UUID
    title: str | None
    abstract: str | None
    content: str | None
