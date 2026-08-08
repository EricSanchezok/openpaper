"""Deterministic local PDF analysis, extraction, and text-only fallback."""

from __future__ import annotations

import logging
import math
import re
import zlib
from importlib.metadata import version
from io import BytesIO

import pymupdf
import pymupdf4llm
from markitdown import MarkItDown
from PIL import Image

from src.pdf.models import (
    LocalPDFAnalysis,
    ParsedDocument,
    ParserBackend,
    ParserContentError,
    ParserQuality,
)

logger = logging.getLogger(__name__)

MIN_FALLBACK_CHARACTERS = 1_000
MIN_PAGE_CHARACTERS = 50
MIN_VALID_PAGE_RATIO = 0.5
MIN_COMPRESSED_TEXT_BYTES = 600
TEXT_ONLY_WARNING_CODE = "text_only_fallback"
MARKITDOWN_WARNING_CODE = "markitdown_fallback"

_markitdown: MarkItDown | None = None


def _non_whitespace_length(value: str) -> int:
    return len(re.sub(r"\s+", "", value))


def _canonical_page_text(
    pages: list[tuple[int, str]],
) -> tuple[str, dict[int, list[int]]]:
    chunks: list[str] = []
    offsets: dict[int, list[int]] = {}
    offset = 0

    for page_number, raw_text in pages:
        text = raw_text.replace("\x00", "").strip()
        if not text:
            continue
        chunk = text if not chunks else f"\n\n{text}"
        start = offset
        chunks.append(chunk)
        offset += len(chunk)
        offsets[page_number] = [start, offset]

    return "".join(chunks), offsets


def _render_preview(document: pymupdf.Document) -> bytes | None:
    try:
        pixmap = document[0].get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))
        image: Image.Image = Image.open(BytesIO(pixmap.tobytes("png")))
        if image.width > 800:
            ratio = 800 / image.width
            image = image.resize(
                (800, int(image.height * ratio)),
                Image.Resampling.LANCZOS,
            )
        output = BytesIO()
        image.save(output, format="WEBP", quality=82, method=6)
        return output.getvalue()
    except Exception:
        logger.warning("paper.pdf_preview.render_failed", exc_info=True)
        return None


def analyze_pdf(pdf_bytes: bytes) -> LocalPDFAnalysis:
    try:
        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
            if document.needs_pass:
                raise ParserContentError("Password-protected PDFs are not supported")
            if len(document) == 0:
                raise ParserContentError("PDF has no pages")

            pages = [
                (
                    page_index + 1,
                    document[page_index].get_text("text", sort=True),
                )
                for page_index in range(len(document))
            ]
            preview_bytes = _render_preview(document)
    except ParserContentError:
        raise
    except (RuntimeError, ValueError) as exc:
        raise ParserContentError("PDF could not be opened locally") from exc

    markdown, page_offset_map = _canonical_page_text(pages)
    page_character_counts = [_non_whitespace_length(text) for _, text in pages]
    return LocalPDFAnalysis(
        markdown=markdown,
        page_offset_map=page_offset_map,
        page_count=len(pages),
        valid_text_pages=sum(
            count >= MIN_PAGE_CHARACTERS for count in page_character_counts
        ),
        non_whitespace_characters=sum(page_character_counts),
        parser_version=f"pymupdf-{version('PyMuPDF')}",
        preview_bytes=preview_bytes,
    )


def is_scanned_candidate(analysis: LocalPDFAnalysis) -> bool:
    """Return True when the text layer is too thin to trust local extraction.

    A PDF is treated as a scan when the native text layer is empty or nearly
    empty, or when the only "text" is repeated boilerplate (e.g. a per-page
    copyright watermark). Genuine prose cannot compress below ~0.55 at small
    sizes, so a low zlib-compressed size is a strong uniqueness signal.
    """
    if analysis.non_whitespace_characters < MIN_FALLBACK_CHARACTERS:
        return True
    required_pages = max(1, math.ceil(analysis.page_count * MIN_VALID_PAGE_RATIO))
    if analysis.valid_text_pages < required_pages:
        return True
    compressed_bytes = len(zlib.compress(analysis.markdown.encode("utf-8", "ignore")))
    return compressed_bytes < MIN_COMPRESSED_TEXT_BYTES


def extract_markdown_pymupdf4llm(
    pdf_path: str,
    *,
    parser_version: str,
) -> ParsedDocument:
    """Extract page-chunked Markdown with exact per-page offsets (primary)."""
    try:
        chunks = pymupdf4llm.to_markdown(
            pdf_path,
            page_chunks=True,
            use_llm=False,
        )
    except Exception as exc:
        raise ParserContentError("pymupdf4llm could not extract text") from exc

    page_chunks: dict[int, str] = {}
    for chunk in chunks:
        page_number = int(chunk["metadata"].get("page_number", 0))
        text = str(chunk.get("text", "")).replace("\x00", "")
        if text.strip():
            page_chunks[page_number] = text

    if not page_chunks:
        raise ParserContentError("pymupdf4llm produced no page text")

    markdown_parts: list[str] = []
    offsets: dict[int, list[int]] = {}
    offset = 0
    for page_number in sorted(page_chunks):
        chunk = page_chunks[page_number]
        if markdown_parts:
            chunk = f"\n\n{chunk}"
        start = offset
        markdown_parts.append(chunk)
        offset += len(chunk)
        offsets[page_number] = [start, offset]

    return ParsedDocument(
        markdown="".join(markdown_parts),
        page_offset_map=offsets,
        backend=ParserBackend.PYMUPDF4LLM,
        quality=ParserQuality.FULL,
        parser_version=parser_version,
    )


def extract_markdown_markitdown(
    pdf_path: str,
    *,
    parser_version: str,
    fallback_offsets: dict[int, list[int]],
) -> ParsedDocument:
    """Extract Markdown with a second engine, degraded to text_only offsets.

    MarkItDown has no page-boundary metadata, so offsets are approximated from
    the deterministic per-page text analysis. This is a degraded tier on
    purpose: consumers that map offsets to pages may drift by at most one page,
    and the `text_only` quality lets the UI warn about layout-dependent gaps.
    """
    global _markitdown
    if _markitdown is None:
        _markitdown = MarkItDown()
    try:
        result = _markitdown.convert_local(pdf_path)
    except Exception as exc:
        raise ParserContentError("MarkItDown could not extract text") from exc
    markdown = str(result.text_content or "").replace("\x00", "")
    if not markdown.strip():
        raise ParserContentError("MarkItDown produced no text")

    return ParsedDocument(
        markdown=markdown,
        page_offset_map=fallback_offsets,
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
        parser_version=parser_version,
        warning_code=MARKITDOWN_WARNING_CODE,
    )


def build_text_last_resort(analysis: LocalPDFAnalysis) -> ParsedDocument:
    """Deterministic per-page text with exact offsets; never calls a new engine."""
    required_pages = max(1, math.ceil(analysis.page_count * MIN_VALID_PAGE_RATIO))
    if (
        analysis.non_whitespace_characters < MIN_FALLBACK_CHARACTERS
        or analysis.valid_text_pages < required_pages
    ):
        raise ParserContentError("PDF does not contain enough native text")

    return ParsedDocument(
        markdown=analysis.markdown,
        page_offset_map=analysis.page_offset_map,
        backend=ParserBackend.PYMUPDF4LLM,
        quality=ParserQuality.TEXT_ONLY,
        parser_version=analysis.parser_version,
        warning_code=TEXT_ONLY_WARNING_CODE,
    )
