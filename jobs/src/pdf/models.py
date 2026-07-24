"""Shared types for the PDF parsing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ParserBackend(StrEnum):
    MINERU = "mineru"
    PYMUPDF = "pymupdf"


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


class ParserTransientError(ParserError):
    """A temporary provider or network failure that may use local fallback."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ParserContentError(ParserError):
    """The document or provider result cannot produce usable content."""


class ParserConfigurationError(ParserError):
    """A required parser credential or runtime setting is invalid."""


class ParserSecurityError(ParserError):
    """An external response failed a security boundary."""
