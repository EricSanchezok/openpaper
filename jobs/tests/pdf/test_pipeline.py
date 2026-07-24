from __future__ import annotations

import asyncio

import pymupdf
import pytest

from src.pdf.mineru import MinerUConfig
from src.pdf.models import (
    LocalPDFAnalysis,
    ParserConfigurationError,
    ParserContentError,
    ParserTransientError,
)
from src.pdf.pipeline import _select_document, process_pdf_file
from src.schemas import PDFProcessingResult, PaperMetadataExtraction


def _usable_local_analysis() -> LocalPDFAnalysis:
    markdown = "local text " * 200
    return LocalPDFAnalysis(
        markdown=markdown,
        page_offset_map={1: [0, len(markdown)]},
        page_count=1,
        valid_text_pages=1,
        non_whitespace_characters=1_800,
        parser_version="pymupdf-test",
        preview_bytes=None,
    )


def test_transient_mineru_failure_uses_text_only_fallback() -> None:
    document = _select_document(
        ParserTransientError("cdn unavailable"),
        _usable_local_analysis(),
        job_id="job-1",
    )

    assert document.backend.value == "pymupdf"
    assert document.quality.value == "text_only"
    assert document.warning_code == "text_only_fallback"


def test_configuration_failure_is_not_hidden_by_fallback() -> None:
    with pytest.raises(ParserConfigurationError):
        _select_document(
            ParserConfigurationError("bad token"),
            _usable_local_analysis(),
            job_id="job-1",
        )


def test_unusable_local_result_keeps_stable_content_failure() -> None:
    with pytest.raises(ParserContentError):
        _select_document(
            ParserTransientError("provider unavailable"),
            ParserContentError("scanned PDF"),
            job_id="job-1",
        )


def test_pdf_processing_result_rejects_half_success() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        PDFProcessingResult(success=True, job_id="job-1", raw_content="text")

    with pytest.raises(ValueError, match="error code"):
        PDFProcessingResult(success=False, job_id="job-1")


def test_development_pipeline_persists_fallback_and_runs_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pymupdf.open()
    for _ in range(2):
        page = document.new_page()
        text = "\n".join(
            f"Scholens pipeline line {index} contains native research text."
            for index in range(30)
        )
        page.insert_textbox((72, 72, 520, 770), text, fontsize=10)
    pdf_bytes = document.tobytes()
    document.close()

    uploaded_names: list[str] = []

    def upload(_payload: bytes, name: str, _content_type: str) -> tuple[str, str]:
        uploaded_names.append(name)
        return f"uploads/{name}", f"https://assets.example/{name}"

    async def extract_metadata(
        _markdown: str,
        *,
        job_id: str,
        status_callback,
    ) -> PaperMetadataExtraction:
        del job_id, status_callback
        return PaperMetadataExtraction(title="Fallback paper")

    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: None),
    )
    monkeypatch.setattr(
        "src.pdf.pipeline.s3_service.upload_any_file_from_bytes",
        upload,
    )
    monkeypatch.setattr(
        "src.pdf.pipeline.s3_service.cloudflare_bucket_name",
        "assets.example",
    )
    monkeypatch.setattr(
        "src.pdf.pipeline.llm_client.extract_paper_metadata",
        extract_metadata,
    )

    result = asyncio.run(
        process_pdf_file(
            pdf_bytes,
            "https://source.example/paper.pdf",
            "uploads/original.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert result.success
    assert result.parser_backend == "pymupdf"
    assert result.parser_quality == "text_only"
    assert result.metadata is not None
    assert result.metadata.title == "Fallback paper"
    assert result.parser_archive_s3_key is None
    assert "job-1-full.md" in uploaded_names
