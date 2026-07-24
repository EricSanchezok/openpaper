from __future__ import annotations

import pymupdf
import pytest

from src.pdf.local import analyze_pdf, build_text_fallback
from src.pdf.models import ParserContentError


def _native_text_pdf(*, pages: int = 2, lines: int = 30) -> bytes:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page()
        text = "\n".join(
            f"Scholens local parsing line {index} contains native research text."
            for index in range(lines)
        )
        page.insert_textbox((72, 72, 520, 770), text, fontsize=10)
    payload = document.tobytes()
    document.close()
    return payload


def test_native_text_fallback_preserves_page_offsets() -> None:
    analysis = analyze_pdf(_native_text_pdf())
    result = build_text_fallback(analysis)

    assert result.backend.value == "pymupdf"
    assert result.quality.value == "text_only"
    assert result.warning_code == "text_only_fallback"
    assert result.page_offset_map.keys() == {1, 2}
    assert (
        "Scholens local parsing line 0"
        in result.markdown[result.page_offset_map[1][0] : result.page_offset_map[1][1]]
    )
    assert analysis.preview_bytes is not None


def test_image_only_pdf_does_not_pretend_to_be_parsed() -> None:
    document = pymupdf.open()
    document.new_page()
    payload = document.tobytes()
    document.close()

    with pytest.raises(ParserContentError, match="enough native text"):
        build_text_fallback(analyze_pdf(payload))


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
