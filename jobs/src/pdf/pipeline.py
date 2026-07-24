"""PDF processing through MinerU, with deterministic local previews."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Callable

from src.llm_client import llm_client
from src.pdf.local import generate_pdf_preview
from src.pdf.mineru import mineru_client
from src.s3_service import s3_service
from src.schemas import PDFProcessingResult, PaperMetadataExtraction
from src.utils import time_it

logger = logging.getLogger(__name__)
MIN_EXTRACTED_TEXT_CHARS = 1000


class UnprocessablePDFError(Exception):
    pass


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return ""


def _block_markdown(block: dict) -> str:
    block_type = str(block.get("type", ""))
    if block_type == "text":
        text = _as_text(block.get("text"))
        level = int(block.get("text_level", 0) or 0)
        return f"{'#' * min(level, 6)} {text}" if level and text else text
    if block_type == "equation":
        return _as_text(block.get("text"))
    if block_type == "table":
        parts = [
            _as_text(block.get("table_caption")),
            _as_text(block.get("table_body")),
            _as_text(block.get("table_footnote")),
        ]
        return "\n\n".join(part for part in parts if part)
    if block_type in {"image", "chart"}:
        parts = [
            _as_text(block.get(f"{block_type}_caption")),
            _as_text(block.get("content")),
            _as_text(block.get(f"{block_type}_footnote")),
        ]
        return "\n\n".join(part for part in parts if part)
    if block_type == "code":
        body = _as_text(block.get("code_body"))
        caption = _as_text(block.get("code_caption"))
        fenced = f"```\n{body}\n```" if body else ""
        return "\n\n".join(part for part in (caption, fenced) if part)
    if block_type == "list":
        return "\n".join(
            f"- {item}" for item in block.get("list_items", []) if str(item).strip()
        )
    if block_type in {"header", "footer", "page_number"}:
        return ""
    return _as_text(block.get("text") or block.get("content"))


def canonical_markdown(
    content_list: list[dict],
) -> tuple[str, dict[int, list[int]]]:
    indexed = list(enumerate(content_list))
    indexed.sort(key=lambda item: (int(item[1].get("page_idx", 0) or 0), item[0]))

    chunks: list[str] = []
    page_offsets: dict[int, list[int]] = {}
    current_page: int | None = None
    page_start = 0
    offset = 0

    for _, block in indexed:
        page = int(block.get("page_idx", 0) or 0) + 1
        text = _block_markdown(block).replace("\x00", "").strip()
        if not text:
            continue
        if current_page is None:
            current_page = page
            page_start = offset
        elif page != current_page:
            page_offsets[current_page] = [page_start, offset]
            current_page = page
            page_start = offset

        chunk = text if not chunks else f"\n\n{text}"
        chunks.append(chunk)
        offset += len(chunk)

    if current_page is not None:
        page_offsets[current_page] = [page_start, offset]
    return "".join(chunks), page_offsets


async def process_pdf_file(
    pdf_bytes: bytes,
    source_url: str,
    s3_object_key: str,
    job_id: str,
    status_callback: Callable[[str], None],
    skip_metadata_extraction: bool = False,
) -> PDFProcessingResult:
    start_time = datetime.now(timezone.utc)
    temp_file_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(pdf_bytes)
            temp_file_path = temp_file.name

        status_callback("Parsing PDF with MinerU")
        if mineru_client is None:
            raise RuntimeError("MinerU is not configured")
        async with time_it("Parsing PDF with MinerU", job_id=job_id):
            mineru_task = asyncio.create_task(
                mineru_client.parse_url(source_url, data_id=job_id)
            )
            preview_task = asyncio.create_task(
                asyncio.to_thread(generate_pdf_preview, temp_file_path)
            )
            mineru_result, preview_result = await asyncio.gather(
                mineru_task, preview_task, return_exceptions=True
            )

        if isinstance(mineru_result, BaseException):
            raise mineru_result
        if isinstance(preview_result, BaseException):
            logger.warning("Preview generation failed for %s", job_id)
            preview_object_key, preview_url = None, None
        else:
            preview_object_key, preview_url = preview_result

        markdown, page_offsets = canonical_markdown(mineru_result.content_list)
        if len(markdown.strip()) < MIN_EXTRACTED_TEXT_CHARS:
            raise UnprocessablePDFError("MinerU returned insufficient paper content")

        markdown_key, _ = await asyncio.to_thread(
            s3_service.upload_any_file_from_bytes,
            markdown.encode("utf-8"),
            f"{job_id}-full.md",
            "text/markdown; charset=utf-8",
        )
        archive_key, _ = await asyncio.to_thread(
            s3_service.upload_any_file_from_bytes,
            mineru_result.archive_bytes,
            f"{job_id}-mineru.zip",
            "application/zip",
        )

        metadata: PaperMetadataExtraction | None = None
        if not skip_metadata_extraction:
            metadata = await llm_client.extract_paper_metadata(
                markdown,
                job_id=job_id,
                status_callback=status_callback,
            )
            if not metadata.title:
                raise ValueError("DeepSeek metadata extraction returned no title")

        return PDFProcessingResult(
            success=True,
            metadata=metadata,
            s3_object_key=s3_object_key,
            file_url=f"https://{s3_service.cloudflare_bucket_name}/{s3_object_key}",
            preview_url=preview_url,
            preview_object_key=preview_object_key,
            parser_markdown_s3_key=markdown_key,
            parser_archive_s3_key=archive_key,
            job_id=job_id,
            raw_content=markdown,
            page_offset_map=page_offsets,
            duration=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )
    except UnprocessablePDFError as exc:
        logger.warning("PDF processing skipped for %s: %s", job_id, exc)
        return PDFProcessingResult(
            success=False,
            error="pdf_content_insufficient",
            job_id=job_id,
        )
    except Exception:
        logger.error("PDF processing failed for %s", job_id, exc_info=True)
        return PDFProcessingResult(
            success=False,
            error="pdf_processing_failed",
            job_id=job_id,
        )
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.unlink(temp_file_path)
