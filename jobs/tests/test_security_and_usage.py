from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("MINERU_API_TOKEN", "test-token")

from src.pdf.mineru import MinerUClient
from src.pdf.pipeline import canonical_markdown
from src.token_usage import collect_token_usage, record_token_usage
from src.webhook_signing import post_signed_json


def _zip(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


def test_mineru_archive_requires_safe_canonical_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    client = MinerUClient()
    result = client._read_archive(
        _zip(
            {
                "result/full.md": "# Paper",
                "result/content_list.json": json.dumps(
                    [{"type": "text", "text": "Paper", "page_idx": 0}]
                ),
            }
        )
    )
    assert result.markdown == "# Paper"
    assert result.content_list[0]["page_idx"] == 0

    with pytest.raises(ValueError, match="Unsafe path"):
        client._read_archive(
            _zip(
                {
                    "../full.md": "# Escape",
                    "content_list.json": "[]",
                }
            )
        )


def test_mineru_rejects_non_public_archive_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MINERU_API_TOKEN", "test-token")
    client = MinerUClient()

    with pytest.raises(ValueError, match="non-public"):
        client._validate_archive_url("https://127.0.0.1/result.zip")


def test_jobs_usage_uses_provider_total_as_the_only_charge() -> None:
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=80,
        total_tokens=180,
        prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=50),
    )
    with collect_token_usage("job-1") as collector:
        record_token_usage(
            feature="metadata",
            model="standard-model",
            usage=usage,
            request_id="request-1",
            idempotency_suffix="metadata",
        )

    assert collector.events[0]["total_tokens"] == 180
    assert collector.events[0]["reasoning_tokens"] == 50
    assert collector.events[0]["idempotency_key"] == "jobs:job-1:metadata"


def test_mineru_content_list_builds_page_aware_canonical_markdown() -> None:
    markdown, offsets = canonical_markdown(
        [
            {"type": "text", "text": "Introduction", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "First page.", "page_idx": 0},
            {"type": "page_number", "text": "2", "page_idx": 1},
            {"type": "equation", "text": "$x = 1$", "page_idx": 1},
        ]
    )

    assert markdown == "# Introduction\n\nFirst page.\n\n$x = 1$"
    assert markdown[offsets[1][0] : offsets[1][1]] == "# Introduction\n\nFirst page."
    assert markdown[offsets[2][0] : offsets[2][1]] == "\n\n$x = 1$"


def test_jobs_webhook_signature_covers_method_target_nonce_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JOBS_WEBHOOK_SIGNING_SECRET", "s" * 32)
    payload = {"status": "completed"}
    expected_body = json.dumps(
        payload, separators=(",", ":"), ensure_ascii=False
    ).encode()

    with (
        patch("src.webhook_signing.time.time", return_value=1_700_000_000),
        patch(
            "src.webhook_signing.uuid.uuid4",
            return_value="00000000-0000-0000-0000-000000000001",
        ),
        patch("src.webhook_signing.requests.post") as post,
    ):
        post_signed_json(
            "https://api.example/api/webhooks/job?attempt=1",
            payload,
            timeout=5,
        )

    headers = post.call_args.kwargs["headers"]
    canonical = "\n".join(
        (
            "1700000000",
            "00000000-0000-0000-0000-000000000001",
            "POST",
            "/api/webhooks/job?attempt=1",
            hashlib.sha256(expected_body).hexdigest(),
        )
    ).encode()
    assert (
        headers["X-Jobs-Signature"]
        == hmac.new(b"s" * 32, canonical, hashlib.sha256).hexdigest()
    )
