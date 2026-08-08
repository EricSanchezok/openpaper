"""Shared types for the PDF parsing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ParserBackend(StrEnum):
    MINERU = "mineru"
    PYMUPDF4LLM = "pymupdf4llm"
    MARKITDOWN = "markitdown"


class ParserQuality(StrEnum):
    FULL = "full"
    TEXT_ONLY = "text_only"


@dataclass(frozen=True)
class ParsedDocument:
    markdown: str
    page_offset_map: dict[int, list[int]]
    backend: ParserBackend
    quality: ParserQuality
    parser_version: str
    warning_code: str | None = None
    archive_bytes: bytes | None = None


@dataclass(frozen=True)
class LocalPDFAnalysis:
    markdown: str
    page_offset_map: dict[int, list[int]]
    page_count: int
    valid_text_pages: int
    non_whitespace_characters: int
    parser_version: str
    preview_bytes: bytes | None


class ParserError(Exception):
    """Base class for errors whose handling is defined by the pipeline."""

    def __init__(
        self,
        message: str,
        *,
        phase: str | None = None,
        task_id: str | None = None,
        mineru_code: str | None = None,
        trace_id: str | None = None,
        http_status: int | None = None,
        exception_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.task_id = task_id
        self.mineru_code = mineru_code
        self.trace_id = trace_id
        self.http_status = http_status
        self.exception_type = exception_type or type(self).__name__

    def diagnostic_fields(self) -> dict[str, str | int]:
        """Return safe, structured diagnostics without credentials or URLs."""
        fields: dict[str, str | int] = {"exception_type": self.exception_type}
        if self.phase is not None:
            fields["phase"] = self.phase
        if self.task_id is not None:
            fields["task_id"] = self.task_id
        if self.mineru_code is not None:
            fields["mineru_code"] = self.mineru_code
        if self.trace_id is not None:
            fields["trace_id"] = self.trace_id
        if self.http_status is not None:
            fields["http_status"] = self.http_status
        return fields


class ParserTransientError(ParserError):
    """A provider or network failure retried until the parsing budget expires."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        phase: str | None = None,
        task_id: str | None = None,
        mineru_code: str | None = None,
        trace_id: str | None = None,
        http_status: int | None = None,
        exception_type: str | None = None,
    ) -> None:
        super().__init__(
            message,
            phase=phase,
            task_id=task_id,
            mineru_code=mineru_code,
            trace_id=trace_id,
            http_status=http_status,
            exception_type=exception_type,
        )
        self.retry_after = retry_after


class ParserContentError(ParserError):
    """The document or provider result cannot produce usable content."""


class ParserConfigurationError(ParserError):
    """A required parser credential or runtime setting is invalid."""


class ParserSecurityError(ParserError):
    """An external response failed a security boundary."""
