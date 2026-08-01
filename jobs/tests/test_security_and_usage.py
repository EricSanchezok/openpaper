from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from scholens_observability import current_context

from src.observability import _task_postrun, _task_prerun
from src.token_usage import collect_token_usage, record_token_usage
from src.webhook_signing import post_signed_json


def test_job_task_context_restores_durable_causality_headers() -> None:
    task = SimpleNamespace(
        name="process_pdf",
        request=SimpleNamespace(
            headers={
                "scholens-correlation-id": "correlation-1",
                "scholens-causation-id": "operation-1",
                "scholens-actor-id": "42",
            }
        ),
    )

    _task_prerun(task_id="job-1", task=task)

    context = current_context()
    assert context.operation_id == "job-1"
    assert context.correlation_id == "correlation-1"
    assert context.causation_id == "operation-1"
    assert context.actor_id == "42"

    _task_postrun(task_id="job-1", task=task, state="SUCCESS")
    assert current_context().operation_id is None


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
