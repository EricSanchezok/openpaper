from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.jobs_webhooks import webhook_router
from app.api.jobs_webhooks.router import handle_paper_parser_upgrade_webhook
from app.api.paper_api import _serialize_paper_for_client
from app.database.models import Document, JobStatus
from app.schemas.jobs import (
    PDFParserUpgradeResult,
    PDFProcessingResult,
    PdfParserUpgradeWebhookData,
    PdfProcessingWebhookData,
)

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

    jobs_upgrade = next(
        node
        for node in jobs_schema.body
        if isinstance(node, ast.ClassDef) and node.name == "PDFParserUpgradeResult"
    )
    upgrade_fields = {
        node.target.id
        for node in jobs_upgrade.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert upgrade_fields == set(PDFParserUpgradeResult.model_fields)


def test_client_paper_contract_hides_parser_provider_details() -> None:
    paper = Document(
        id=uuid4(),
        file_url="https://example.invalid/paper.pdf",
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


def test_parser_upgrade_contract_is_full_only_and_strict() -> None:
    payload = PdfParserUpgradeWebhookData(
        task_id="job-1:mineru-upgrade",
        result=PDFParserUpgradeResult(
            job_id="job-1",
            raw_content="full MinerU text",
            page_offset_map={1: [0, 17]},
            parser_markdown_s3_key="uploads/pdf-parses/job-1/full.md",
            parser_archive_s3_key="uploads/pdf-parses/job-1/mineru.zip",
            parser_version="mineru-v4/vlm",
        ),
    )

    assert payload.result.parser_quality == "full"
    assert payload.result.parser_warning_code is None
    with pytest.raises(ValidationError):
        PDFParserUpgradeResult.model_validate(
            {
                **payload.result.model_dump(),
                "parser_quality": "text_only",
            }
        )


def test_parser_upgrade_webhook_is_registered() -> None:
    paths = {route.path for route in webhook_router.routes}
    assert "/paper-parser-upgrade/{job_id}" in paths


def test_parser_upgrade_replaces_content_and_passages_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    paper = Document(
        id=uuid4(),
        upload_job_id=job_id,
        raw_content="text-only content",
        parser_quality="text_only",
        parser_backend="pymupdf",
        parser_version="pymupdf-test",
        parser_warning_code="text_only_fallback",
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = paper
    index_passages = MagicMock()
    release_lock = MagicMock()
    monkeypatch.setattr(
        "app.api.jobs_webhooks.router.paper_upload_job_crud.get_by",
        MagicMock(return_value=SimpleNamespace(status=JobStatus.COMPLETED)),
    )
    monkeypatch.setattr(
        "app.api.jobs_webhooks.router.AdvisoryLock.acquire",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        "app.api.jobs_webhooks.router.AdvisoryLock.release",
        release_lock,
    )
    monkeypatch.setattr(
        "app.api.jobs_webhooks.router.paper_crud.index_paper_passages",
        index_passages,
    )
    payload = PdfParserUpgradeWebhookData(
        task_id=f"{job_id}:mineru-upgrade",
        result=PDFParserUpgradeResult(
            job_id=str(job_id),
            raw_content="full MinerU content",
            page_offset_map={1: [0, 20]},
            parser_markdown_s3_key=f"uploads/pdf-parses/{job_id}/full.md",
            parser_archive_s3_key=f"uploads/pdf-parses/{job_id}/mineru.zip",
            parser_version="mineru-v4/vlm",
        ),
    )

    response = handle_paper_parser_upgrade_webhook(
        str(job_id),
        payload,
        db,
    )

    assert response["status"] == "parser upgrade applied"
    assert paper.raw_content == "full MinerU content"
    assert paper.page_offset_map == {1: [0, 20]}
    assert paper.parser_backend == "mineru"
    assert paper.parser_quality == "full"
    assert paper.parser_warning_code is None
    index_passages.assert_called_once_with(
        db,
        paper_id=paper.id,
        raw_content="full MinerU content",
    )
    db.commit.assert_called_once()
    release_lock.assert_called_once()
