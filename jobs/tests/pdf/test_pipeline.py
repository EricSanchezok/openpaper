from __future__ import annotations

import asyncio

import pymupdf
import pytest

from src.pdf.mineru import MinerUConfig
from src.pdf.models import (
    LocalPDFAnalysis,
    ParsedDocument,
    ParserBackend,
    ParserConfigurationError,
    ParserContentError,
    ParserQuality,
    ParserTransientError,
)
from src.pdf.pipeline import (
    _select_document,
    process_pdf_file,
    upgrade_pdf_from_checkpoint,
)
from src.schemas import PDFProcessingResult, PaperMetadataExtraction


def _mineru_config() -> MinerUConfig:
    return MinerUConfig(
        token="test-token",
        base_url="https://mineru.example/api/v4",
        model_version="vlm",
        poll_seconds=0.001,
        task_timeout_seconds=1,
        request_timeout_seconds=1,
        max_archive_bytes=4 * 1024 * 1024,
    )


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

    def upload(_payload: bytes, key: str, _content_type: str) -> str:
        uploaded_names.append(key)
        return key

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
        "src.pdf.pipeline.s3_service.upload_bytes_to_key",
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
            f"documents/{'a' * 64}/source.pdf",
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
    assert f"documents/{'a' * 64}/canonical.md" in uploaded_names


def test_transient_fallback_preserves_checkpoint_for_automatic_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = pymupdf.open()
    for page_number in range(2):
        page = document.new_page()
        page.insert_textbox(
            (72, 72, 520, 770),
            "\n".join(
                f"Usable local research text line {page_number}-{index}."
                for index in range(30)
            ),
            fontsize=10,
        )
    pdf_bytes = document.tobytes()
    document.close()

    class MemoryState:
        cleared = False

        async def get_task_id(self, _job_id: str) -> str | None:
            return "running-mineru-task"

        async def save_source_key(self, _job_id: str, _source_key: str) -> None:
            return None

        async def clear(self, _job_id: str) -> None:
            self.cleared = True

    state = MemoryState()

    class FailingMinerUClient:
        def __init__(self, _config: MinerUConfig) -> None:
            self.state_store = state

        async def parse_url(self, _source_url: str, *, data_id: str) -> ParsedDocument:
            raise ParserTransientError(
                "poll deadline expired",
                phase="poll",
                task_id="running-mineru-task",
            )

        async def close(self) -> None:
            return None

    async def extract_metadata(
        _markdown: str,
        *,
        job_id: str,
        status_callback,
    ) -> PaperMetadataExtraction:
        del job_id, status_callback
        return PaperMetadataExtraction(title="Fallback with pending upgrade")

    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: _mineru_config()),
    )
    monkeypatch.setattr("src.pdf.pipeline.MinerUClient", FailingMinerUClient)
    monkeypatch.setattr(
        "src.pdf.pipeline.s3_service.upload_bytes_to_key",
        lambda _payload, key, _content_type: key,
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
            f"documents/{'b' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert result.success
    assert result.parser_quality == "text_only"
    assert result.parser_upgrade_pending is True
    assert state.cleared is False


def test_upgrade_resumes_checkpoint_and_uses_idempotent_artifact_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    markdown = "MinerU full content " * 100
    parsed = ParsedDocument(
        markdown=markdown,
        page_offset_map={1: [0, len(markdown)]},
        backend=ParserBackend.MINERU,
        quality=ParserQuality.FULL,
        parser_version="mineru-v4/vlm",
        archive_bytes=b"zip-audit-artifact",
    )
    uploaded: list[tuple[str, str]] = []

    class UpgradeMinerUClient:
        def __init__(self, _config: MinerUConfig) -> None:
            self.state_store = self

        async def get_source_key(self, _job_id: str) -> str | None:
            return f"documents/{'c' * 64}/source.pdf"

        async def parse_existing(self, *, data_id: str) -> ParsedDocument:
            assert data_id == "job-1"
            return parsed

        async def close(self) -> None:
            return None

    def upload_to_key(_payload: bytes, key: str, content_type: str) -> str:
        uploaded.append((key, content_type))
        return key

    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: _mineru_config()),
    )
    monkeypatch.setattr("src.pdf.pipeline.MinerUClient", UpgradeMinerUClient)
    monkeypatch.setattr(
        "src.pdf.pipeline.s3_service.upload_bytes_to_key",
        upload_to_key,
    )

    result = asyncio.run(upgrade_pdf_from_checkpoint("job-1"))

    assert result.parser_quality == "full"
    assert result.parser_warning_code is None
    assert result.parser_markdown_s3_key == f"documents/{'c' * 64}/canonical.md"
    assert result.parser_archive_s3_key == (f"documents/{'c' * 64}/mineru-result.zip")
    assert sorted(uploaded) == [
        (
            f"documents/{'c' * 64}/canonical.md",
            "text/markdown; charset=utf-8",
        ),
        (f"documents/{'c' * 64}/mineru-result.zip", "application/zip"),
    ]
