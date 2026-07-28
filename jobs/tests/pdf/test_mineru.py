from __future__ import annotations

import asyncio
import io
import json
import zipfile

import httpx
import pytest

from src.pdf.mineru import MinerUClient, MinerUConfig, canonical_markdown
from src.pdf.models import (
    ParserConfigurationError,
    ParserSecurityError,
    ParserTransientError,
)


class MemoryStateStore:
    def __init__(self, task_id: str | None = None) -> None:
        self.task_id = task_id
        self.lock_token: str | None = None

    async def get_task_id(self, _job_id: str) -> str | None:
        return self.task_id

    async def save_task_id(self, _job_id: str, task_id: str) -> None:
        self.task_id = task_id

    async def clear(self, _job_id: str) -> None:
        self.task_id = None

    async def acquire_submit_lock(self, _job_id: str) -> str | None:
        if self.lock_token is not None:
            return None
        self.lock_token = "lock-token"
        return self.lock_token

    async def wait_for_task_id(self, _job_id: str) -> str | None:
        return self.task_id

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


def test_resumes_existing_task_without_resubmitting(
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
            json={
                "code": 0,
                "data": {
                    "state": "done",
                    "full_zip_url": "https://cdn.example/result.zip",
                },
            },
            request=request,
        )

    monkeypatch.setattr(
        MinerUClient, "_validate_archive_url", staticmethod(lambda _: None)
    )
    client = MinerUClient(
        _config(),
        MemoryStateStore("existing-task"),
        transport=httpx.MockTransport(handler),
    )
    phases: list[tuple[str, str | None]] = []

    result = asyncio.run(
        client.parse_url(
            "https://source.example/paper.pdf",
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
            return httpx.Response(
                200,
                json={"code": 0, "data": {"task_id": "task-1"}},
                request=request,
            )
        if request.url.host == "cdn.example":
            calls["download"] += 1
            if calls["download"] == 1:
                raise httpx.ConnectError("connection reset", request=request)
            return httpx.Response(200, content=archive_bytes, request=request)
        calls["poll"] += 1
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "state": "done",
                    "full_zip_url": "https://cdn.example/result.zip",
                },
            },
            request=request,
        )

    monkeypatch.setattr(
        MinerUClient, "_validate_archive_url", staticmethod(lambda _: None)
    )
    monkeypatch.setattr(MinerUClient, "_backoff", staticmethod(_no_backoff))
    client = MinerUClient(
        _config(),
        MemoryStateStore(),
        transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(
        client.parse_url("https://source.example/paper.pdf", data_id="job-1")
    )

    assert result.quality.value == "full"
    assert calls == {"post": 1, "download": 2, "poll": 2}


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
            json={
                "code": 0,
                "data": {
                    "state": "done",
                    "full_zip_url": "https://cdn.example/result.zip",
                },
            },
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

    result = asyncio.run(
        client.parse_url("https://source.example/paper.pdf", data_id="job-1")
    )

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
            client.parse_url(
                "https://source.example/paper.pdf",
                data_id="job-1",
            )
        )
    assert calls == 1


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
            client.parse_url(
                "https://source.example/paper.pdf",
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
            json={
                "code": 0,
                "data": {
                    "state": "done",
                    "full_zip_url": "https://cdn.example/result.zip",
                },
            },
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

    result = asyncio.run(
        client.parse_url("https://source.example/paper.pdf", data_id="job-1")
    )

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
