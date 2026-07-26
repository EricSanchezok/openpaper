"""Deterministic PyMuPDF analysis and text-only fallback."""

from __future__ import annotations

import logging
import math
import re
from importlib.metadata import version
from io import BytesIO

import pymupdf
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
FALLBACK_WARNING_CODE = "text_only_fallback"


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
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except Exception:
        logger.warning("PDF preview rendering failed", exc_info=True)
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


def build_text_fallback(analysis: LocalPDFAnalysis) -> ParsedDocument:
    required_pages = max(1, math.ceil(analysis.page_count * MIN_VALID_PAGE_RATIO))
    if (
        analysis.non_whitespace_characters < MIN_FALLBACK_CHARACTERS
        or analysis.valid_text_pages < required_pages
    ):
        raise ParserContentError("PDF does not contain enough native text")

    return ParsedDocument(
        markdown=analysis.markdown,
        page_offset_map=analysis.page_offset_map,
        backend=ParserBackend.PYMUPDF,
        quality=ParserQuality.TEXT_ONLY,
        parser_version=analysis.parser_version,
        warning_code=FALLBACK_WARNING_CODE,
    )
