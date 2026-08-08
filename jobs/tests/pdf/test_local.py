from __future__ import annotations

import pymupdf
import pytest

from src.pdf.local import (
    analyze_pdf,
    build_text_last_resort,
    extract_markdown_markitdown,
    extract_markdown_pymupdf4llm,
    is_scanned_candidate,
)
from src.pdf.models import ParserContentError

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


def _native_text_pdf(*, pages: int = 2, lines: int = 30) -> bytes:
    """A digital PDF whose text layer passes the scan gate (high entropy)."""
    document = pymupdf.open()
    for page_number in range(pages):
        page = document.new_page()
        text = "\n".join(
            f"Scholens line {page_number}-{index} studies "
            f"{_TOPICS[(page_number * lines + index) % len(_TOPICS)]}."
            for index in range(lines)
        )
        page.insert_textbox((72, 72, 520, 770), text, fontsize=10)
    payload = document.tobytes()
    document.close()
    return payload


def _boilerplate_watermark_pdf() -> bytes:
    """Repeated per-page boilerplate that defeats raw char counts."""
    document = pymupdf.open()
    for _ in range(20):
        page = document.new_page()
        text = "\n".join(["Copyright \u00a9 ProQuest. All rights reserved."] * 30)
        page.insert_textbox((72, 72, 520, 770), text, fontsize=10)
    payload = document.tobytes()
    document.close()
    return payload


def test_analyze_pdf_produces_offsets_and_preview() -> None:
    analysis = analyze_pdf(_native_text_pdf())

    assert analysis.page_offset_map.keys() == {1, 2}
    assert (
        "Scholens line 0"
        in analysis.markdown[
            analysis.page_offset_map[1][0] : analysis.page_offset_map[1][1]
        ]
    )
    assert analysis.preview_bytes is not None
    assert analysis.valid_text_pages == 2


def test_digital_pdf_is_not_a_scanned_candidate() -> None:
    analysis = analyze_pdf(_native_text_pdf())
    assert not is_scanned_candidate(analysis)


def test_image_only_pdf_is_a_scanned_candidate() -> None:
    document = pymupdf.open()
    document.new_page()
    payload = document.tobytes()
    document.close()

    assert is_scanned_candidate(analyze_pdf(payload))


def test_watermark_boilerplate_is_a_scanned_candidate() -> None:
    analysis = analyze_pdf(_boilerplate_watermark_pdf())
    # Raw character count is high, but the unique content is tiny.
    assert analysis.non_whitespace_characters > 1_000
    assert is_scanned_candidate(analysis)


def test_pymupdf4llm_extraction_is_full_with_exact_offsets(tmp_path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(_native_text_pdf())

    result = extract_markdown_pymupdf4llm(
        str(pdf_path),
        parser_version="pymupdf-test",
    )

    assert result.backend.value == "pymupdf4llm"
    assert result.quality.value == "full"
    assert result.warning_code is None
    assert result.page_offset_map.keys() == {1, 2}
    # Offsets are exact against the produced markdown string.
    for page_number, (start, end) in result.page_offset_map.items():
        assert start < end <= len(result.markdown)
    assert "Scholens line 0" in result.markdown


def test_markitdown_extraction_is_text_only_degraded(tmp_path) -> None:
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(_native_text_pdf())
    offsets = {1: [0, 10], 2: [11, 20]}

    result = extract_markdown_markitdown(
        str(pdf_path),
        parser_version="pymupdf-test",
        fallback_offsets=offsets,
    )

    assert result.backend.value == "markitdown"
    assert result.quality.value == "text_only"
    assert result.warning_code == "markitdown_fallback"
    assert result.page_offset_map == offsets
    assert "Scholens line" in result.markdown


def test_pymupdf4llm_rejects_unreadable_file(tmp_path) -> None:
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"not a pdf")

    with pytest.raises(ParserContentError, match="pymupdf4llm"):
        extract_markdown_pymupdf4llm(str(pdf_path), parser_version="test")


def test_last_resort_preserves_exact_page_offsets() -> None:
    analysis = analyze_pdf(_native_text_pdf())
    result = build_text_last_resort(analysis)

    assert result.backend.value == "pymupdf4llm"
    assert result.quality.value == "text_only"
    assert result.warning_code == "text_only_fallback"
    assert result.page_offset_map == analysis.page_offset_map
    assert (
        "Scholens line 0"
        in result.markdown[result.page_offset_map[1][0] : result.page_offset_map[1][1]]
    )


def test_last_resort_rejects_scanned_pdf() -> None:
    document = pymupdf.open()
    document.new_page()
    payload = document.tobytes()
    document.close()

    with pytest.raises(ParserContentError, match="enough native text"):
        build_text_last_resort(analyze_pdf(payload))


def test_password_protected_pdf_is_rejected() -> None:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "Private paper")
    payload = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="reader-secret",
    )
    document.close()

    with pytest.raises(ParserContentError, match="Password-protected"):
        analyze_pdf(payload)
