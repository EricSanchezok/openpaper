from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.paper_api import _serialize_paper_for_client
from app.database.models import Paper
from app.schemas.jobs import PDFProcessingResult, PdfProcessingWebhookData

ROOT = Path(__file__).resolve().parents[2]


def _successful_result() -> dict:
    return {
        "success": True,
        "job_id": "job-1",
        "raw_content": "paper text",
        "page_offset_map": {1: [0, 10]},
        "parser_backend": "pymupdf",
        "parser_quality": "text_only",
        "parser_version": "pymupdf-test",
        "parser_warning_code": "text_only_fallback",
    }


def test_pdf_jobs_contract_accepts_complete_degraded_result() -> None:
    payload = PdfProcessingWebhookData(
        task_id="task-1",
        status="completed",
        result=PDFProcessingResult.model_validate(_successful_result()),
    )

    assert payload.result.parser_quality == "text_only"
    assert payload.result.parser_warning_code == "text_only_fallback"


def test_pdf_jobs_contract_rejects_half_success_and_extra_fields() -> None:
    incomplete = _successful_result()
    incomplete.pop("parser_version")
    with pytest.raises(ValidationError, match="incomplete"):
        PDFProcessingResult.model_validate(incomplete)

    extra = _successful_result()
    extra["provider_internal_error"] = "do not leak"
    with pytest.raises(ValidationError, match="Extra inputs"):
        PDFProcessingResult.model_validate(extra)


def test_pdf_jobs_contract_requires_stable_failure_code() -> None:
    with pytest.raises(ValidationError, match="error code"):
        PDFProcessingResult.model_validate({"success": False, "job_id": "job-1"})


def test_pdf_result_fields_match_jobs_producer_contract() -> None:
    jobs_schema = ast.parse(
        (ROOT / "jobs" / "src" / "schemas.py").read_text(encoding="utf-8")
    )
    jobs_result = next(
        node
        for node in jobs_schema.body
        if isinstance(node, ast.ClassDef) and node.name == "PDFProcessingResult"
    )
    producer_fields = {
        node.target.id
        for node in jobs_result.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }

    assert producer_fields == set(PDFProcessingResult.model_fields)


def test_client_paper_contract_hides_parser_provider_details() -> None:
    paper = Paper(
        id=uuid4(),
        status="reading",
        file_url="https://example.invalid/paper.pdf",
        last_accessed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        parser_backend="mineru",
        parser_version="mineru-v4/vlm",
        parser_quality="text_only",
        parser_warning_code="text_only_fallback",
    )
    result = _serialize_paper_for_client(paper)

    assert "parser_backend" not in result
    assert "parser_version" not in result
    assert result["parser_quality"] == "text_only"
