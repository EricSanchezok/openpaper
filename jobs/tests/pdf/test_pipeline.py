from __future__ import annotations

import asyncio

import pymupdf
import pytest

from src.pdf.mineru import MinerUConfig
from src.pdf.models import (
    ParsedDocument,
    ParserBackend,
    ParserConfigurationError,
    ParserContentError,
    ParserQuality,
    ParserTransientError,
)
from src.pdf.pipeline import process_pdf_file
from src.schemas import PDFProcessingResult, PaperMetadataExtraction

_TOPICS = [
    "attention mechanisms",
    "graph neural networks",
    "reinforcement learning",
    "diffusion models",
    "retrieval augmented generation",
    "mixture of experts",
    "quantization",
    "pruning",
    "knowledge distillation",
    "contrastive learning",
    "federated learning",
    "self-supervised pretraining",
    "neural architecture search",
    "prompt engineering",
    "chain-of-thought reasoning",
    "vector databases",
    "sparse attention",
    "rotary embeddings",
    "flash attention",
    "low-rank adapters",
    "speculative decoding",
    "context distillation",
    "activation sparsity",
    "model merging",
    "test-time scaling",
    "reasoning traces",
    "tool use",
    "multi-modal alignment",
    "token efficiency",
    "training stability",
    "gradient clipping",
    "weight decay",
    "learning rate schedules",
    "data augmentation",
    "curriculum learning",
    "meta learning",
    "few-shot prompting",
    "in-context learning",
    "latent space geometry",
    "embedding alignment",
    "nearest neighbor search",
    "semantic hashing",
    "ensemble methods",
    "bayesian optimization",
    "gaussian processes",
    "monte carlo methods",
    "markov chains",
    "entropy estimation",
    "mutual information",
    "causal inference",
    "counterfactual reasoning",
    "ablative analysis",
    "hyperparameter tuning",
    "early stopping",
    "batch normalization",
    "layer normalization",
    "residual connections",
    "positional encoding",
    "tokenization strategies",
    "byte pair encoding",
]


def _digital_pdf() -> bytes:
    """A digital PDF whose text layer passes the scan gate (high entropy)."""
    document = pymupdf.open()
    for page_number in range(2):
        page = document.new_page()
        text = "\n".join(
            f"Scholens line {page_number}-{index} studies "
            f"{_TOPICS[(page_number * 30 + index) % len(_TOPICS)]}."
            for index in range(30)
        )
        page.insert_textbox((72, 72, 520, 770), text, fontsize=10)
    payload = document.tobytes()
    document.close()
    return payload


def _scanned_pdf() -> bytes:
    document = pymupdf.open()
    document.new_page()
    payload = document.tobytes()
    document.close()
    return payload


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


def _full_mineru_document() -> ParsedDocument:
    return ParsedDocument(
        markdown="mineru markdown " * 50,
        page_offset_map={1: [0, 750]},
        backend=ParserBackend.MINERU,
        quality=ParserQuality.FULL,
        parser_version="mineru-test",
        archive_bytes=b"PK\x03\x04mineru-archive",
    )


def _markitdown_document() -> ParsedDocument:
    return ParsedDocument(
        markdown="markitdown markdown " * 50,
        page_offset_map={1: [0, 1000]},
        backend=ParserBackend.MARKITDOWN,
        quality=ParserQuality.TEXT_ONLY,
        parser_version="markitdown-test",
        warning_code="markitdown_fallback",
    )


class _FakeMinerUClient:
    def __init__(self, _config: MinerUConfig) -> None:
        pass

    async def parse_file(
        self,
        _pdf_bytes: bytes,
        *,
        data_id: str,
        deadline: float | None = None,
    ) -> ParsedDocument:
        del data_id, deadline
        return _full_mineru_document()

    async def close(self) -> None:
        return None


class _FailingMinerUClient:
    def __init__(self, _config: MinerUConfig) -> None:
        pass

    async def parse_file(
        self,
        _pdf_bytes: bytes,
        *,
        data_id: str,
        deadline: float | None = None,
    ) -> ParsedDocument:
        del data_id, deadline
        raise ParserTransientError(
            "poll deadline expired",
            phase="poll",
            task_id="running-mineru-batch",
        )

    async def close(self) -> None:
        return None


def _patch_s3(monkeypatch: pytest.MonkeyPatch, uploaded: list[str]) -> None:
    def upload(_payload: bytes, key: str, _content_type: str) -> str:
        uploaded.append(key)
        return key

    monkeypatch.setattr(
        "src.pdf.pipeline.s3_service.upload_bytes_to_key",
        upload,
    )
    monkeypatch.setattr(
        "src.pdf.pipeline.s3_service.cloudflare_bucket_name",
        "assets.example",
    )


def _patch_metadata(monkeypatch: pytest.MonkeyPatch, title: str) -> None:
    async def extract_metadata(
        _markdown: str,
        *,
        job_id: str,
        status_callback,
    ) -> PaperMetadataExtraction:
        del job_id, status_callback
        return PaperMetadataExtraction(title=title)

    monkeypatch.setattr(
        "src.pdf.pipeline.llm_client.extract_paper_metadata",
        extract_metadata,
    )


def test_digital_pdf_uses_pymupdf4llm_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded: list[str] = []
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: None),
    )
    _patch_s3(monkeypatch, uploaded)
    _patch_metadata(monkeypatch, "Digital paper")

    result = asyncio.run(
        process_pdf_file(
            _digital_pdf(),
            f"documents/{'a' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert result.success
    assert result.parser_backend == "pymupdf4llm"
    assert result.parser_quality == "full"
    assert result.parser_warning_code is None
    assert result.parser_archive_s3_key is None
    assert result.metadata is not None
    assert result.page_offset_map is not None
    assert set(result.page_offset_map) == {1, 2}
    assert f"documents/{'a' * 64}/canonical.md" in uploaded


def test_pymupdf4llm_failure_falls_back_to_markitdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_pymupdf4llm(_path: str, **_: object) -> ParsedDocument:
        raise ParserContentError("pymupdf4llm could not extract text")

    monkeypatch.setattr(
        "src.pdf.pipeline.extract_markdown_pymupdf4llm",
        failing_pymupdf4llm,
    )
    monkeypatch.setattr(
        "src.pdf.pipeline.extract_markdown_markitdown",
        lambda _path, **_: _markitdown_document(),
    )
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: None),
    )
    _patch_s3(monkeypatch, [])
    _patch_metadata(monkeypatch, "Markitdown paper")

    result = asyncio.run(
        process_pdf_file(
            _digital_pdf(),
            f"documents/{'b' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert result.success
    assert result.parser_backend == "markitdown"
    assert result.parser_quality == "text_only"
    assert result.parser_warning_code == "markitdown_fallback"


def test_local_failure_rescues_via_mineru_with_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_local(_path: str, **_: object) -> ParsedDocument:
        raise ParserContentError("local extraction failed")

    monkeypatch.setattr(
        "src.pdf.pipeline.extract_markdown_pymupdf4llm",
        failing_local,
    )
    monkeypatch.setattr(
        "src.pdf.pipeline.extract_markdown_markitdown",
        failing_local,
    )
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: _mineru_config()),
    )
    monkeypatch.setattr("src.pdf.pipeline.MinerUClient", _FakeMinerUClient)
    uploaded: list[str] = []
    _patch_s3(monkeypatch, uploaded)
    _patch_metadata(monkeypatch, "Rescued paper")

    result = asyncio.run(
        process_pdf_file(
            _digital_pdf(),
            f"documents/{'c' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert result.success
    assert result.parser_backend == "mineru"
    assert result.parser_quality == "full"
    assert result.parser_archive_s3_key == f"documents/{'c' * 64}/mineru-result.zip"
    assert f"documents/{'c' * 64}/mineru-result.zip" in uploaded


def test_mineru_rescue_timeout_uses_text_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_local(_path: str, **_: object) -> ParsedDocument:
        raise ParserContentError("local extraction failed")

    monkeypatch.setattr(
        "src.pdf.pipeline.extract_markdown_pymupdf4llm",
        failing_local,
    )
    monkeypatch.setattr(
        "src.pdf.pipeline.extract_markdown_markitdown",
        failing_local,
    )
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: _mineru_config()),
    )
    monkeypatch.setattr("src.pdf.pipeline.MinerUClient", _FailingMinerUClient)
    _patch_s3(monkeypatch, [])
    _patch_metadata(monkeypatch, "Last resort paper")

    result = asyncio.run(
        process_pdf_file(
            _digital_pdf(),
            f"documents/{'d' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert result.success
    assert result.parser_backend == "pymupdf4llm"
    assert result.parser_quality == "text_only"
    assert result.parser_warning_code == "text_only_fallback"
    assert result.parser_archive_s3_key is None
    assert set(result.page_offset_map or {}) == {1, 2}


def test_scanned_pdf_goes_directly_to_mineru(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: _mineru_config()),
    )
    monkeypatch.setattr("src.pdf.pipeline.MinerUClient", _FakeMinerUClient)
    uploaded: list[str] = []
    _patch_s3(monkeypatch, uploaded)
    _patch_metadata(monkeypatch, "Scanned paper")

    result = asyncio.run(
        process_pdf_file(
            _scanned_pdf(),
            f"documents/{'e' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert result.success
    assert result.parser_backend == "mineru"
    assert result.parser_quality == "full"
    assert result.parser_archive_s3_key == f"documents/{'e' * 64}/mineru-result.zip"


def test_scanned_pdf_with_mineru_failure_returns_content_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: _mineru_config()),
    )
    monkeypatch.setattr("src.pdf.pipeline.MinerUClient", _FailingMinerUClient)
    _patch_s3(monkeypatch, [])

    result = asyncio.run(
        process_pdf_file(
            _scanned_pdf(),
            f"documents/{'f' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
        )
    )

    assert not result.success
    assert result.error == "pdf_content_insufficient"


def test_scanned_pdf_without_mineru_config_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: None),
    )

    with pytest.raises(ParserConfigurationError):
        asyncio.run(
            process_pdf_file(
                _scanned_pdf(),
                f"documents/{'1' * 64}/source.pdf",
                "job-1",
                status_callback=lambda _status: None,
            )
        )


def test_skip_metadata_extraction_skips_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        MinerUConfig,
        "from_env",
        classmethod(lambda _cls: None),
    )
    _patch_s3(monkeypatch, [])

    def unexpected_llm_call(*_args: object, **_: object) -> None:
        raise AssertionError("metadata extraction must be skipped")

    monkeypatch.setattr(
        "src.pdf.pipeline.llm_client.extract_paper_metadata",
        unexpected_llm_call,
    )

    result = asyncio.run(
        process_pdf_file(
            _digital_pdf(),
            f"documents/{'2' * 64}/source.pdf",
            "job-1",
            status_callback=lambda _status: None,
            skip_metadata_extraction=True,
        )
    )

    assert result.success
    assert result.parser_backend == "pymupdf4llm"
    assert result.metadata is None


def test_pdf_processing_result_rejects_half_success() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        PDFProcessingResult(success=True, job_id="job-1", raw_content="text")

    with pytest.raises(ValueError, match="error code"):
        PDFProcessingResult(success=False, job_id="job-1")
