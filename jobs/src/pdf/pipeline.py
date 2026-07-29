"""Orchestration for high-fidelity and degraded PDF parsing."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Callable

from src.llm_client import llm_client
from src.pdf.local import analyze_pdf, build_text_fallback
from src.pdf.mineru import MinerUClient, MinerUConfig
from src.pdf.models import (
    LocalPDFAnalysis,
    ParsedDocument,
    ParserConfigurationError,
    ParserContentError,
    ParserSecurityError,
    ParserTransientError,
)
from src.s3_service import s3_service
from src.schemas import (
    PDFProcessingResult,
    PaperMetadataExtraction,
)
from src.utils import time_it

logger = logging.getLogger(__name__)


async def _upload_preview(
    analysis: LocalPDFAnalysis | BaseException,
    document_sha256: str,
) -> str | None:
    if isinstance(analysis, BaseException) or analysis.preview_bytes is None:
        return None
    try:
        object_key = _document_artifact_key(document_sha256, "preview.webp")
        await asyncio.to_thread(
            s3_service.upload_bytes_to_key,
            analysis.preview_bytes,
            object_key,
            "image/webp",
        )
        return object_key
    except Exception:
        logger.warning("Preview upload failed for %s", document_sha256, exc_info=True)
        return None


def _select_document(
    mineru_result: ParsedDocument | BaseException | None,
    local_result: LocalPDFAnalysis | BaseException,
    *,
    job_id: str,
) -> ParsedDocument:
    if isinstance(mineru_result, ParsedDocument):
        return mineru_result
    if isinstance(mineru_result, (ParserConfigurationError, ParserSecurityError)):
        raise mineru_result
    if isinstance(mineru_result, (ParserContentError, ParserTransientError)):
        diagnostics = mineru_result.diagnostic_fields()
        logger.warning(
            "MinerU parsing reached its terminal fallback boundary; "
            "using local text extraction; diagnostics=%s",
            diagnostics,
            extra={"job_id": job_id, **diagnostics},
        )
    elif mineru_result is not None:
        raise mineru_result
    if isinstance(local_result, BaseException):
        if isinstance(local_result, ParserContentError):
            raise local_result
        raise ParserContentError("Local PDF analysis failed") from local_result
    return build_text_fallback(local_result)


def _document_sha256_from_source_key(s3_object_key: str) -> str:
    match = re.fullmatch(r"documents/([0-9a-f]{64})/source\.pdf", s3_object_key)
    if match is None:
        raise ParserSecurityError(
            "Canonical source key is invalid",
            phase="source",
        )
    return match.group(1)


def _document_artifact_key(document_sha256: str, filename: str) -> str:
    return f"documents/{document_sha256}/{filename}"


async def _upload_full_parser_artifacts(
    document: ParsedDocument,
    *,
    document_sha256: str,
) -> tuple[str, str]:
    if document.archive_bytes is None:
        raise ParserContentError(
            "MinerU full parse has no audit archive",
            phase="archive",
        )
    markdown_key = _document_artifact_key(document_sha256, "canonical.md")
    archive_key = _document_artifact_key(document_sha256, "mineru-result.zip")
    await asyncio.gather(
        asyncio.to_thread(
            s3_service.upload_bytes_to_key,
            document.markdown.encode("utf-8"),
            markdown_key,
            "text/markdown; charset=utf-8",
        ),
        asyncio.to_thread(
            s3_service.upload_bytes_to_key,
            document.archive_bytes,
            archive_key,
            "application/zip",
        ),
    )
    return markdown_key, archive_key


async def process_pdf_file(
    pdf_bytes: bytes,
    s3_object_key: str,
    job_id: str,
    status_callback: Callable[[str], None],
    skip_metadata_extraction: bool = False,
) -> PDFProcessingResult:
    start_time = datetime.now(timezone.utc)
    mineru_client: MinerUClient | None = None
    config = MinerUConfig.from_env()
    document_sha256 = _document_sha256_from_source_key(s3_object_key)

    try:
        local_task = asyncio.create_task(asyncio.to_thread(analyze_pdf, pdf_bytes))
        mineru_task: asyncio.Task[ParsedDocument] | None = None

        if config is not None:
            status_callback("Parsing PDF with MinerU")
            mineru_client = MinerUClient(config)
            mineru_task = asyncio.create_task(
                mineru_client.parse_file(
                    pdf_bytes,
                    data_id=job_id,
                )
            )
        else:
            status_callback("Indexing PDF in local text mode")

        async with time_it("Parsing PDF", job_id=job_id):
            if mineru_task is None:
                local_result = await asyncio.gather(
                    local_task,
                    return_exceptions=True,
                )
                parsed_local = local_result[0]
                mineru_result: ParsedDocument | BaseException | None = None
            else:
                mineru_result, parsed_local = await asyncio.gather(
                    mineru_task,
                    local_task,
                    return_exceptions=True,
                )

        document = _select_document(
            mineru_result,
            parsed_local,
            job_id=job_id,
        )
        if document.quality == "text_only":
            status_callback("MinerU unavailable; using final text-only fallback")

        preview_object_key = await _upload_preview(
            parsed_local,
            document_sha256,
        )

        archive_key: str | None = None
        if document.archive_bytes is not None:
            markdown_key, archive_key = await _upload_full_parser_artifacts(
                document,
                document_sha256=document_sha256,
            )
        else:
            markdown_key = _document_artifact_key(document_sha256, "canonical.md")
            await asyncio.to_thread(
                s3_service.upload_bytes_to_key,
                document.markdown.encode("utf-8"),
                markdown_key,
                "text/markdown; charset=utf-8",
            )

        metadata: PaperMetadataExtraction | None = None
        if not skip_metadata_extraction:
            metadata = await llm_client.extract_paper_metadata(
                document.markdown,
                job_id=job_id,
                status_callback=status_callback,
            )
            if not metadata.title:
                raise ValueError("DeepSeek metadata extraction returned no title")

        return PDFProcessingResult(
            success=True,
            metadata=metadata,
            s3_object_key=s3_object_key,
            preview_s3_key=preview_object_key,
            parser_markdown_s3_key=markdown_key,
            parser_archive_s3_key=archive_key,
            parser_backend=document.backend.value,
            parser_quality=document.quality.value,
            parser_version=document.parser_version,
            parser_warning_code=document.warning_code,
            job_id=job_id,
            raw_content=document.markdown,
            page_offset_map=document.page_offset_map,
            duration=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )
    except ParserContentError as exc:
        logger.warning("PDF content is insufficient for %s: %s", job_id, exc)
        return PDFProcessingResult(
            success=False,
            error="pdf_content_insufficient",
            job_id=job_id,
            duration=(datetime.now(timezone.utc) - start_time).total_seconds(),
        )
    finally:
        if mineru_client is not None:
            await mineru_client.close()
