from __future__ import annotations

import asyncio
import io
import json
import time
import zipfile

import httpx
import pytest

from src.pdf.mineru import MinerUClient, MinerUConfig, canonical_markdown
from src.pdf.models import (
    ParserConfigurationError,
    ParserSecurityError,
    ParserTransientError,
)
from src.pdf.state import MinerUBatchCheckpoint


class MemoryStateStore:
    def __init__(self, batch_id: str | None = None, *, uploaded: bool = True) -> None:
        self.checkpoint = (
            MinerUBatchCheckpoint(
                batch_id=batch_id,
                upload_url="https://upload.example/paper.pdf",
                uploaded=uploaded,
            )
            if batch_id
            else None
        )
        self.lock_token: str | None = None

    async def get_checkpoint(self, _job_id: str) -> MinerUBatchCheckpoint | None:
        return self.checkpoint

    async def save_checkpoint(
        self,
        _job_id: str,
        checkpoint: MinerUBatchCheckpoint,
    ) -> None:
        self.checkpoint = checkpoint

    async def mark_uploaded(self, _job_id: str) -> MinerUBatchCheckpoint:
        assert self.checkpoint is not None
        self.checkpoint = MinerUBatchCheckpoint(
            batch_id=self.checkpoint.batch_id,
            upload_url=self.checkpoint.upload_url,
            uploaded=True,
        )
        return self.checkpoint

    async def clear(self, _job_id: str) -> None:
        self.checkpoint = None

    async def acquire_submit_lock(self, _job_id: str) -> str | None:
        if self.lock_token is not None:
            return None
        self.lock_token = "lock-token"
        return self.lock_token

    async def wait_for_checkpoint(self, _job_id: str) -> MinerUBatchCheckpoint | None:
        return self.checkpoint

    async def release_submit_lock(self, _job_id: str, token: str) -> None:
        if self.lock_token == token:
            self.lock_token = None

    async def close(self) -> None:
        return None


def _config() -> MinerUConfig:
    return MinerUConfig(
        token="test-token",
        base_url="https://mineru.example/api/v4",
        model_version="vlm",
        poll_seconds=0.001,
        task_timeout_seconds=1,
        request_timeout_seconds=1,
        max_archive_bytes=4 * 1024 * 1024,
    )


def _archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("result/full.md", "# Paper")
        archive.writestr(
            "result/content_list.json",
            json.dumps(
                [
                    {
                        "type": "text",
                        "text": "Native MinerU paper text " * 80,
                        "page_idx": 0,
                    }
                ]
            ),
        )
    return output.getvalue()


def _batch_result(
    *,
    state: str = "done",
    archive_url: str = "https://cdn.example/result.zip",
) -> dict:
    result = {
        "data_id": "job-1",
        "state": state,
    }
    if state == "done":
        result["full_zip_url"] = archive_url
    return {
        "code": 0,
        "data": {
            "batch_id": "batch-1",
            "extract_result": [result],
        },
    }


async def _no_backoff(
    _attempt: int,
    _error: ParserTransientError,
    **_kwargs: object,
) -> None:
    return None


def test_archive_requires_safe_canonical_artifacts() -> None:
    client = MinerUClient(_config(), MemoryStateStore())
    result = client.read_archive(_archive())

    assert result.backend.value == "mineru"
    assert result.quality.value == "full"
    assert result.page_offset_map == {1: [0, len(result.markdown)]}

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../full.md", "# Escape")
        archive.writestr("content_list.json", "[]")
    with pytest.raises(ParserSecurityError, match="Unsafe path"):
        client.read_archive(output.getvalue())


def test_archive_rejects_unsafe_compression_ratio() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("full.md", "# Paper")
        archive.writestr("content_list.json", "0" * 100_000)

    client = MinerUClient(_config(), MemoryStateStore())
    with pytest.raises(ParserSecurityError, match="compression ratio"):
        client.read_archive(output.getvalue())


def test_rejects_non_public_archive_url() -> None:
    with pytest.raises(ParserSecurityError, match="non-public"):
        MinerUClient._validate_archive_url("https://127.0.0.1/result.zip")


def test_content_list_builds_page_aware_canonical_markdown() -> None:
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


def test_resumes_existing_batch_without_resubmitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"post": 0}
    archive_bytes = _archive()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["post"] += 1
            return httpx.Response(500, request=request)
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=archive_bytes, request=request)
        return httpx.Response(
            200,
            json=_batch_result(),
            request=request,
        )

    monkeypatch.setattr(
        MinerUClient, "_validate_archive_url", staticmethod(lambda _: None)
    )
    monkeypatch.setattr(
        MinerUClient, "_validate_external_url", staticmethod(lambda _: None)
    )
    client = MinerUClient(
        _config(),
        MemoryStateStore("existing-task"),
        transport=httpx.MockTransport(handler),
    )
    phases: list[tuple[str, str | None]] = []

    result = asyncio.run(
        client.parse_file(
            b"%PDF-test",
            data_id="job-1",
            phase_callback=lambda phase, task_id: phases.append((phase, task_id)),
        )
    )

    assert result.quality.value == "full"
    assert calls["post"] == 0
    assert phases == [
        ("submit", None),
        ("poll", "existing-task"),
        ("download", "existing-task"),
        ("archive", "existing-task"),
    ]


def test_download_retry_refreshes_task_without_resubmitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"post": 0, "download": 0, "poll": 0}
    archive_bytes = _archive()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["post"] += 1
            assert request.url.path == "/api/v4/file-urls/batch"
            assert request.headers["authorization"] == "Bearer test-token"
            assert json.loads(request.content) == {
                "files": [
                    {
                        "name": "job-1.pdf",
                        "data_id": "job-1",
                        "is_ocr": True,
                    }
                ],
                "model_version": "vlm",
                "enable_formula": True,
                "enable_table": True,
            }
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-1",
                        "file_urls": ["https://upload.example/paper.pdf"],
                    },
                },
                request=request,
            )
        if request.method == "PUT":
            assert "authorization" not in request.headers
            assert "content-type" not in request.headers
            assert request.content == b"%PDF-test"
            return httpx.Response(200, request=request)
        if request.url.host == "cdn.example":
            calls["download"] += 1
            if calls["download"] == 1:
                raise httpx.ConnectError("connection reset", request=request)
            return httpx.Response(200, content=archive_bytes, request=request)
        calls["poll"] += 1
        assert request.url.path == "/api/v4/extract-results/batch/batch-1"
        return httpx.Response(
            200,
            json=_batch_result(),
            request=request,
        )

    monkeypatch.setattr(
        MinerUClient, "_validate_archive_url", staticmethod(lambda _: None)
    )
    monkeypatch.setattr(
        MinerUClient, "_validate_external_url", staticmethod(lambda _: None)
    )
    monkeypatch.setattr(MinerUClient, "_backoff", staticmethod(_no_backoff))
    client = MinerUClient(
        _config(),
        MemoryStateStore(),
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(client.parse_file(b"%PDF-test", data_id="job-1"))

    assert result.quality.value == "full"
    assert calls == {"post": 1, "download": 2, "poll": 2}


def test_resumes_incomplete_batch_and_retries_upload_without_resubmitting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"post": 0, "upload": 0}
    archive_bytes = _archive()
    state = MemoryStateStore("batch-1", uploaded=False)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["post"] += 1
            return httpx.Response(500, request=request)
        if request.method == "PUT":
            calls["upload"] += 1
            if calls["upload"] == 1:
                raise httpx.ConnectError("response lost", request=request)
            return httpx.Response(200, request=request)
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=archive_bytes, request=request)
        return httpx.Response(200, json=_batch_result(), request=request)

    monkeypatch.setattr(
        MinerUClient, "_validate_external_url", staticmethod(lambda _: None)
    )
    monkeypatch.setattr(
        MinerUClient, "_validate_archive_url", staticmethod(lambda _: None)
    )
    monkeypatch.setattr(MinerUClient, "_backoff", staticmethod(_no_backoff))
    client = MinerUClient(
        _config(),
        state,
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(client.parse_file(b"%PDF-test", data_id="job-1"))

    assert result.quality.value == "full"
    assert calls == {"post": 0, "upload": 2}
    assert state.checkpoint is not None
    assert state.checkpoint.uploaded is True


def test_download_survives_more_than_four_consecutive_tls_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"download": 0, "poll": 0}
    archive_bytes = _archive()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            calls["download"] += 1
            if calls["download"] <= 5:
                raise httpx.ConnectError("TLS handshake failed", request=request)
            return httpx.Response(200, content=archive_bytes, request=request)
        calls["poll"] += 1
        return httpx.Response(
            200,
            json=_batch_result(),
            request=request,
        )

    monkeypatch.setattr(
        MinerUClient,
        "_validate_archive_url",
        staticmethod(lambda _: None),
    )
    monkeypatch.setattr(MinerUClient, "_backoff", staticmethod(_no_backoff))
    client = MinerUClient(
        _config(),
        MemoryStateStore("existing-task"),
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(client.parse_file(b"%PDF-test", data_id="job-1"))

    assert result.quality.value == "full"
    assert calls == {"download": 6, "poll": 6}


def test_submit_transport_failure_is_not_blindly_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("response lost", request=request)

    client = MinerUClient(
        _config(),
        MemoryStateStore(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ParserTransientError, match="submit"):
        asyncio.run(
            client.parse_file(
                b"%PDF-test",
                data_id="job-1",
            )
        )
    assert calls == 1


def test_expired_foreground_budget_does_not_submit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, request=request)

    client = MinerUClient(
        _config(),
        MemoryStateStore(),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ParserTransientError, match="budget is exhausted"):
        asyncio.run(
            client.parse_file(
                b"%PDF-test",
                data_id="job-1",
                deadline=time.monotonic() - 1,
            )
        )
    assert calls == 0


def test_authorization_failure_is_configuration_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    client = MinerUClient(
        _config(),
        MemoryStateStore(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ParserConfigurationError, match="authorization"):
        asyncio.run(
            client.parse_file(
                b"%PDF-test",
                data_id="job-1",
            )
        )


def test_poll_survives_more_than_four_consecutive_network_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    archive_bytes = _archive()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=archive_bytes, request=request)
        calls += 1
        if calls <= 5:
            raise httpx.ConnectTimeout("temporary TLS failure", request=request)
        return httpx.Response(
            200,
            json=_batch_result(),
            request=request,
        )

    monkeypatch.setattr(
        MinerUClient,
        "_validate_archive_url",
        staticmethod(lambda _: None),
    )
    monkeypatch.setattr(MinerUClient, "_backoff", staticmethod(_no_backoff))
    client = MinerUClient(
        _config(),
        MemoryStateStore("existing-task"),
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(client.parse_file(b"%PDF-test", data_id="job-1"))

    assert result.quality.value == "full"
    assert calls == 6


def test_transient_error_carries_safe_structured_diagnostics() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={"x-trace-id": "trace-123"},
            request=request,
        )

    client = MinerUClient(
        _config(),
        MemoryStateStore("task-123"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ParserTransientError) as captured:
        asyncio.run(
            client.parse_existing(
                data_id="job-1",
            )
        )

    assert captured.value.diagnostic_fields() == {
        "phase": "poll",
        "task_id": "task-123",
        "trace_id": "trace-123",
        "http_status": 503,
        "exception_type": "ParserTransientError",
    }
