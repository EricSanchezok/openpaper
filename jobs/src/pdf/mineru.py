"""Resumable MinerU v4 parsing with bounded network retries."""

from __future__ import annotations

import asyncio
import ipaddress
import io
import json
import logging
import os
import random
import socket
import time
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import urljoin, urlsplit

import httpx

from src.pdf.models import (
    ParsedDocument,
    ParserBackend,
    ParserConfigurationError,
    ParserContentError,
    ParserError,
    ParserQuality,
    ParserSecurityError,
    ParserTransientError,
)
from src.pdf.state import (
    MinerUBatchCheckpoint,
    ParserStateStore,
    ParserTaskState,
)

logger = logging.getLogger(__name__)

FAST_RETRY_ATTEMPTS = 4
SLOW_POLL_BACKOFF_SECONDS = 15.0
MAX_SLOW_POLL_BACKOFF_SECONDS = 30.0
MAX_ARCHIVE_REDIRECTS = 3
MAX_ARCHIVE_ENTRIES = 10_000
MAX_COMPRESSION_RATIO = 200
MIN_EXTRACTED_TEXT_CHARACTERS = 1_000
TRANSIENT_API_CODES = {
    "-10001",
    "-60001",
    "-60007",
    "-60008",
    "-60009",
    "-60010",
    "-60022",
}
CONFIGURATION_API_CODES = {"A0202", "A0211"}


@dataclass(frozen=True)
class MinerUConfig:
    token: str
    base_url: str
    model_version: str
    poll_seconds: float
    task_timeout_seconds: float
    request_timeout_seconds: float
    max_archive_bytes: int

    @classmethod
    def from_env(cls) -> MinerUConfig | None:
        token = os.getenv("MINERU_API_TOKEN")
        environment = os.getenv("ENVIRONMENT", "development").lower()
        if not token:
            if environment == "production":
                raise ParserConfigurationError(
                    "MINERU_API_TOKEN is required in production"
                )
            return None

        base_url = os.getenv("MINERU_API_BASE_URL", "https://mineru.net/api/v4").rstrip(
            "/"
        )
        if environment == "production" and urlsplit(base_url).scheme != "https":
            raise ParserConfigurationError(
                "MINERU_API_BASE_URL must use HTTPS in production"
            )

        try:
            poll_seconds = float(os.getenv("MINERU_POLL_INTERVAL_SECONDS", "3"))
            task_timeout_seconds = float(
                os.getenv("MINERU_TASK_TIMEOUT_SECONDS", "600")
            )
            request_timeout_seconds = float(
                os.getenv("MINERU_REQUEST_TIMEOUT_SECONDS", "60")
            )
            max_archive_bytes = int(
                os.getenv("MINERU_MAX_ARCHIVE_BYTES", str(256 * 1024 * 1024))
            )
        except ValueError as exc:
            raise ParserConfigurationError(
                "MinerU numeric configuration is invalid"
            ) from exc
        if (
            min(
                poll_seconds,
                task_timeout_seconds,
                request_timeout_seconds,
                max_archive_bytes,
            )
            <= 0
        ):
            raise ParserConfigurationError(
                "MinerU timeouts and size limits must be positive"
            )

        return cls(
            token=token,
            base_url=base_url,
            model_version=os.getenv("MINERU_MODEL_VERSION", "vlm"),
            poll_seconds=poll_seconds,
            task_timeout_seconds=task_timeout_seconds,
            request_timeout_seconds=request_timeout_seconds,
            max_archive_bytes=max_archive_bytes,
        )


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return ""


def _block_markdown(block: dict) -> str:
    block_type = str(block.get("type", ""))
    if block_type == "text":
        text = _as_text(block.get("text"))
        level = int(block.get("text_level", 0) or 0)
        return f"{'#' * min(level, 6)} {text}" if level and text else text
    if block_type == "equation":
        return _as_text(block.get("text"))
    if block_type == "table":
        parts = [
            _as_text(block.get("table_caption")),
            _as_text(block.get("table_body")),
            _as_text(block.get("table_footnote")),
        ]
        return "\n\n".join(part for part in parts if part)
    if block_type in {"image", "chart"}:
        parts = [
            _as_text(block.get(f"{block_type}_caption")),
            _as_text(block.get("content")),
            _as_text(block.get(f"{block_type}_footnote")),
        ]
        return "\n\n".join(part for part in parts if part)
    if block_type == "code":
        body = _as_text(block.get("code_body"))
        caption = _as_text(block.get("code_caption"))
        fenced = f"```\n{body}\n```" if body else ""
        return "\n\n".join(part for part in (caption, fenced) if part)
    if block_type == "list":
        return "\n".join(
            f"- {item}" for item in block.get("list_items", []) if str(item).strip()
        )
    if block_type in {"header", "footer", "page_number"}:
        return ""
    return _as_text(block.get("text") or block.get("content"))


def canonical_markdown(
    content_list: list[dict],
) -> tuple[str, dict[int, list[int]]]:
    indexed = list(enumerate(content_list))
    try:
        indexed.sort(key=lambda item: (int(item[1].get("page_idx", 0) or 0), item[0]))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ParserContentError("MinerU content list contains invalid blocks") from exc

    chunks: list[str] = []
    page_offsets: dict[int, list[int]] = {}
    current_page: int | None = None
    page_start = 0
    offset = 0

    for _, block in indexed:
        if not isinstance(block, dict):
            raise ParserContentError("MinerU content list contains invalid blocks")
        try:
            page = int(block.get("page_idx", 0) or 0) + 1
            text = _block_markdown(block).replace("\x00", "").strip()
        except (TypeError, ValueError) as exc:
            raise ParserContentError(
                "MinerU content list contains invalid blocks"
            ) from exc
        if not text:
            continue
        if current_page is None:
            current_page = page
            page_start = offset
        elif page != current_page:
            page_offsets[current_page] = [page_start, offset]
            current_page = page
            page_start = offset

        chunk = text if not chunks else f"\n\n{text}"
        chunks.append(chunk)
        offset += len(chunk)

    if current_page is not None:
        page_offsets[current_page] = [page_start, offset]
    return "".join(chunks), page_offsets


class MinerUClient:
    def __init__(
        self,
        config: MinerUConfig | None = None,
        state_store: ParserTaskState | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        resolved_config = config or MinerUConfig.from_env()
        if resolved_config is None:
            raise ParserConfigurationError("MinerU is not configured")
        self.config = resolved_config
        self.state_store = state_store or ParserStateStore()
        self.transport = transport
        self.headers = {"Authorization": f"Bearer {self.config.token}"}

    @staticmethod
    def _add_error_context(
        error: ParserError,
        *,
        phase: str,
        task_id: str | None,
    ) -> ParserError:
        if error.phase is None:
            error.phase = phase
        if error.task_id is None:
            error.task_id = task_id
        return error

    def _api_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(self.config.request_timeout_seconds),
            follow_redirects=False,
            transport=self.transport,
        )

    def _download_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.request_timeout_seconds),
            follow_redirects=False,
            transport=self.transport,
        )

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("retry-after")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            return None

    @staticmethod
    def _trace_id(
        response: httpx.Response | None = None,
        payload: dict | None = None,
    ) -> str | None:
        if response is not None:
            for name in ("x-trace-id", "trace-id", "x-request-id"):
                value = response.headers.get(name)
                if value:
                    return value[:160]
        if payload is not None:
            for name in ("trace_id", "traceId", "request_id", "requestId"):
                value = payload.get(name)
                if isinstance(value, str) and value:
                    return value[:160]
        return None

    @classmethod
    def _classify_response(
        cls,
        response: httpx.Response,
        phase: str,
        *,
        task_id: str | None,
    ) -> None:
        trace_id = cls._trace_id(response)
        if response.status_code in {401, 403}:
            raise ParserConfigurationError(
                f"MinerU authorization failed during {phase}",
                phase=phase,
                task_id=task_id,
                trace_id=trace_id,
                http_status=response.status_code,
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise ParserTransientError(
                f"MinerU is temporarily unavailable during {phase}",
                retry_after=cls._retry_after(response),
                phase=phase,
                task_id=task_id,
                trace_id=trace_id,
                http_status=response.status_code,
            )
        if response.status_code >= 400:
            raise ParserContentError(
                f"MinerU rejected the document during {phase}",
                phase=phase,
                task_id=task_id,
                trace_id=trace_id,
                http_status=response.status_code,
            )

    @classmethod
    def _classify_payload(
        cls,
        payload: dict,
        phase: str,
        *,
        response: httpx.Response,
        task_id: str | None,
    ) -> None:
        code = str(payload.get("code", "0"))
        if code in {"0", "None"}:
            return
        trace_id = cls._trace_id(response, payload)
        if code in CONFIGURATION_API_CODES:
            raise ParserConfigurationError(
                f"MinerU credentials failed during {phase}",
                phase=phase,
                task_id=task_id,
                mineru_code=code[:80],
                trace_id=trace_id,
                http_status=response.status_code,
            )
        if code in TRANSIENT_API_CODES:
            raise ParserTransientError(
                f"MinerU is temporarily unavailable during {phase}",
                phase=phase,
                task_id=task_id,
                mineru_code=code[:80],
                trace_id=trace_id,
                http_status=response.status_code,
            )
        raise ParserContentError(
            f"MinerU rejected the document during {phase}",
            phase=phase,
            task_id=task_id,
            mineru_code=code[:80],
            trace_id=trace_id,
            http_status=response.status_code,
        )

    async def _json_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        phase: str,
        json_body: dict | None = None,
        task_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict:
        try:
            response = await client.request(
                method,
                url,
                json=json_body,
                timeout=(
                    timeout_seconds
                    if timeout_seconds is not None
                    else self.config.request_timeout_seconds
                ),
            )
        except httpx.TransportError as exc:
            raise ParserTransientError(
                f"MinerU network failure during {phase}",
                phase=phase,
                task_id=task_id,
                exception_type=type(exc).__name__,
            ) from exc
        self._classify_response(response, phase, task_id=task_id)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ParserTransientError(
                f"MinerU returned invalid JSON during {phase}",
                phase=phase,
                task_id=task_id,
                trace_id=self._trace_id(response),
                http_status=response.status_code,
                exception_type=type(exc).__name__,
            ) from exc
        if not isinstance(payload, dict):
            raise ParserTransientError(
                f"MinerU returned an invalid response during {phase}",
                phase=phase,
                task_id=task_id,
                trace_id=self._trace_id(response),
                http_status=response.status_code,
            )
        self._classify_payload(
            payload,
            phase,
            response=response,
            task_id=task_id,
        )
        return payload

    async def request_upload(
        self,
        client: httpx.AsyncClient,
        *,
        data_id: str,
    ) -> MinerUBatchCheckpoint:
        payload = await self._json_request(
            client,
            "POST",
            f"{self.config.base_url}/file-urls/batch",
            phase="submit",
            json_body={
                "files": [
                    {
                        "name": f"{data_id}.pdf",
                        "data_id": data_id,
                        "is_ocr": True,
                    }
                ],
                "model_version": self.config.model_version,
                "enable_formula": True,
                "enable_table": True,
            },
        )
        data = payload.get("data") or {}
        batch_id = data.get("batch_id")
        file_urls = data.get("file_urls")
        if (
            not isinstance(batch_id, str)
            or not batch_id
            or not isinstance(file_urls, list)
            or len(file_urls) != 1
            or not isinstance(file_urls[0], str)
            or not file_urls[0]
        ):
            raise ParserTransientError(
                "MinerU response did not include a batch upload target",
                phase="submit",
                trace_id=self._trace_id(payload=payload),
            )
        return MinerUBatchCheckpoint(
            batch_id=batch_id,
            upload_url=file_urls[0],
        )

    async def _get_or_create_batch(
        self,
        client: httpx.AsyncClient,
        *,
        data_id: str,
    ) -> MinerUBatchCheckpoint:
        checkpoint = await self.state_store.get_checkpoint(data_id)
        if checkpoint is not None:
            return checkpoint

        lock_token = await self.state_store.acquire_submit_lock(data_id)
        if lock_token is None:
            checkpoint = await self.state_store.wait_for_checkpoint(data_id)
            if checkpoint is not None:
                return checkpoint
            raise ParserTransientError("Timed out waiting for MinerU batch submission")

        try:
            checkpoint = await self.state_store.get_checkpoint(data_id)
            if checkpoint is not None:
                return checkpoint
            checkpoint = await self.request_upload(client, data_id=data_id)
            await self.state_store.save_checkpoint(data_id, checkpoint)
            return checkpoint
        finally:
            try:
                await self.state_store.release_submit_lock(data_id, lock_token)
            except ParserTransientError:
                logger.warning(
                    "Could not release MinerU submit lock for %s",
                    data_id,
                    exc_info=True,
                )

    async def upload_file(
        self,
        upload_url: str,
        pdf_bytes: bytes,
        *,
        batch_id: str,
        deadline: float,
    ) -> None:
        try:
            await asyncio.to_thread(self._validate_external_url, upload_url)
        except ParserError as exc:
            raise self._add_error_context(
                exc,
                phase="upload",
                task_id=batch_id,
            )
        attempt = 0
        last_error: ParserTransientError | None = None
        async with self._download_client() as client:
            while time.monotonic() < deadline:
                attempt += 1
                remaining = deadline - time.monotonic()
                try:
                    response = await client.put(
                        upload_url,
                        content=pdf_bytes,
                        timeout=min(self.config.request_timeout_seconds, remaining),
                    )
                    if 300 <= response.status_code < 400:
                        raise ParserSecurityError(
                            "MinerU upload target redirected unexpectedly",
                            phase="upload",
                            task_id=batch_id,
                            http_status=response.status_code,
                        )
                    if response.status_code == 429 or response.status_code >= 500:
                        raise ParserTransientError(
                            "MinerU upload target is temporarily unavailable",
                            retry_after=self._retry_after(response),
                            phase="upload",
                            task_id=batch_id,
                            http_status=response.status_code,
                        )
                    if response.status_code >= 400:
                        raise ParserTransientError(
                            "MinerU upload target rejected the file",
                            phase="upload",
                            task_id=batch_id,
                            http_status=response.status_code,
                        )
                    return
                except httpx.TransportError as exc:
                    last_error = ParserTransientError(
                        "MinerU file upload failed",
                        phase="upload",
                        task_id=batch_id,
                        exception_type=type(exc).__name__,
                    )
                except ParserTransientError as exc:
                    last_error = exc
                logger.warning(
                    "MinerU upload failed; retrying the idempotent PUT; diagnostics=%s",
                    json.dumps(last_error.diagnostic_fields(), sort_keys=True),
                    extra={
                        **last_error.diagnostic_fields(),
                        "attempt": attempt,
                    },
                )
                await self._backoff(
                    attempt,
                    last_error,
                    deadline=deadline,
                    slow_after_fast_failures=True,
                )
        if last_error is not None:
            raise ParserTransientError(
                f"MinerU batch {batch_id} upload deadline expired",
                phase="upload",
                task_id=batch_id,
                trace_id=last_error.trace_id,
                http_status=last_error.http_status,
                exception_type=last_error.exception_type,
            ) from last_error
        raise ParserTransientError(
            f"MinerU batch {batch_id} upload deadline expired",
            phase="upload",
            task_id=batch_id,
        )

    async def get_batch_result(
        self,
        client: httpx.AsyncClient,
        batch_id: str,
        *,
        data_id: str,
        timeout_seconds: float | None = None,
    ) -> dict:
        payload = await self._json_request(
            client,
            "GET",
            f"{self.config.base_url}/extract-results/batch/{batch_id}",
            phase="poll",
            task_id=batch_id,
            timeout_seconds=timeout_seconds,
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise ParserTransientError(
                "MinerU batch status is invalid",
                phase="poll",
                task_id=batch_id,
            )
        results = data.get("extract_result")
        if not isinstance(results, list):
            raise ParserTransientError(
                "MinerU batch result list is invalid",
                phase="poll",
                task_id=batch_id,
            )
        for result in results:
            if isinstance(result, dict) and result.get("data_id") == data_id:
                return result
        if len(results) == 1 and isinstance(results[0], dict):
            return results[0]
        raise ParserTransientError(
            "MinerU batch result is missing the requested document",
            phase="poll",
            task_id=batch_id,
        )

    @staticmethod
    def _backoff_seconds(
        attempt: int,
        error: ParserTransientError,
        *,
        slow_after_fast_failures: bool = False,
    ) -> float:
        if error.retry_after is not None:
            return error.retry_after
        if slow_after_fast_failures and attempt > FAST_RETRY_ATTEMPTS:
            slow_attempt = attempt - FAST_RETRY_ATTEMPTS
            return min(
                MAX_SLOW_POLL_BACKOFF_SECONDS,
                SLOW_POLL_BACKOFF_SECONDS + (slow_attempt - 1) * 3,
            ) + random.uniform(0, 0.5)
        return min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.25)

    @classmethod
    async def _backoff(
        cls,
        attempt: int,
        error: ParserTransientError,
        *,
        deadline: float | None = None,
        slow_after_fast_failures: bool = False,
    ) -> None:
        delay = cls._backoff_seconds(
            attempt,
            error,
            slow_after_fast_failures=slow_after_fast_failures,
        )
        if deadline is not None:
            delay = min(delay, max(0.0, deadline - time.monotonic()))
        if delay > 0:
            await asyncio.sleep(delay)

    async def _get_status_until_deadline(
        self,
        client: httpx.AsyncClient,
        batch_id: str,
        *,
        data_id: str,
        deadline: float,
    ) -> dict:
        last_error: ParserTransientError | None = None
        consecutive_failures = 0
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            try:
                return await self.get_batch_result(
                    client,
                    batch_id,
                    data_id=data_id,
                    timeout_seconds=min(
                        self.config.request_timeout_seconds,
                        remaining,
                    ),
                )
            except ParserTransientError as exc:
                last_error = exc
                consecutive_failures += 1
                logger.warning(
                    "MinerU poll failed; retrying within the task deadline; "
                    "diagnostics=%s",
                    json.dumps(exc.diagnostic_fields(), sort_keys=True),
                    extra={
                        **exc.diagnostic_fields(),
                        "consecutive_failures": consecutive_failures,
                        "retry_mode": (
                            "slow"
                            if consecutive_failures > FAST_RETRY_ATTEMPTS
                            else "fast"
                        ),
                    },
                )
                await self._backoff(
                    consecutive_failures,
                    exc,
                    deadline=deadline,
                    slow_after_fast_failures=True,
                )
        if last_error is not None:
            raise ParserTransientError(
                f"MinerU batch {batch_id} polling deadline expired",
                phase="poll",
                task_id=batch_id,
                mineru_code=last_error.mineru_code,
                trace_id=last_error.trace_id,
                http_status=last_error.http_status,
                exception_type=last_error.exception_type,
            ) from last_error
        raise ParserTransientError(
            f"MinerU batch {batch_id} polling deadline expired",
            phase="poll",
            task_id=batch_id,
        )

    async def poll_batch(
        self,
        client: httpx.AsyncClient,
        batch_id: str,
        *,
        data_id: str,
        deadline: float | None = None,
    ) -> str:
        lifecycle_deadline = (
            deadline
            if deadline is not None
            else time.monotonic() + self.config.task_timeout_seconds
        )
        while time.monotonic() < lifecycle_deadline:
            data = await self._get_status_until_deadline(
                client,
                batch_id,
                data_id=data_id,
                deadline=lifecycle_deadline,
            )
            state = str(data.get("state", "")).lower()
            if state == "done":
                archive_url = data.get("full_zip_url")
                if not archive_url or not isinstance(archive_url, str):
                    raise ParserTransientError(
                        "MinerU completed without an archive URL",
                        phase="poll",
                        task_id=batch_id,
                    )
                return archive_url
            if state == "failed":
                raise ParserContentError(
                    "MinerU could not parse the document",
                    phase="poll",
                    task_id=batch_id,
                    mineru_code=str(data.get("err_code") or "")[:80] or None,
                    trace_id=str(data.get("trace_id") or "")[:160] or None,
                )
            remaining = lifecycle_deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(min(self.config.poll_seconds, remaining))
        raise ParserTransientError(
            f"MinerU batch {batch_id} timed out",
            phase="poll",
            task_id=batch_id,
        )

    @staticmethod
    def _validate_external_url(url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ParserSecurityError("MinerU URL must be a public HTTPS URL")
        try:
            addresses = socket.getaddrinfo(
                parsed.hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ParserTransientError("MinerU host could not be resolved") from exc
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_global for address in addresses
        ):
            raise ParserSecurityError("MinerU URL resolved to a non-public address")

    _validate_archive_url = _validate_external_url

    async def _download_once(
        self,
        client: httpx.AsyncClient,
        initial_url: str,
        *,
        task_id: str,
    ) -> bytes:
        url = initial_url
        for redirect_count in range(MAX_ARCHIVE_REDIRECTS + 1):
            try:
                await asyncio.to_thread(self._validate_archive_url, url)
            except ParserError as exc:
                raise self._add_error_context(
                    exc,
                    phase="download",
                    task_id=task_id,
                )
            try:
                async with client.stream("GET", url) as response:
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("location")
                        if not location:
                            raise ParserSecurityError(
                                "MinerU archive redirect has no location"
                            )
                        if redirect_count == MAX_ARCHIVE_REDIRECTS:
                            raise ParserSecurityError(
                                "MinerU archive exceeded redirect limit"
                            )
                        url = urljoin(url, location)
                        continue
                    if response.status_code == 429 or response.status_code >= 500:
                        raise ParserTransientError(
                            "MinerU archive service is unavailable",
                            retry_after=self._retry_after(response),
                            phase="download",
                            task_id=task_id,
                            trace_id=self._trace_id(response),
                            http_status=response.status_code,
                        )
                    if response.status_code >= 400:
                        raise ParserTransientError(
                            "MinerU archive URL is unavailable",
                            phase="download",
                            task_id=task_id,
                            trace_id=self._trace_id(response),
                            http_status=response.status_code,
                        )

                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError as exc:
                            raise ParserSecurityError(
                                "MinerU archive has invalid content length"
                            ) from exc
                        if declared_size > self.config.max_archive_bytes:
                            raise ParserSecurityError(
                                "MinerU archive exceeds configured size limit"
                            )

                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.config.max_archive_bytes:
                            raise ParserSecurityError(
                                "MinerU archive exceeds configured size limit"
                            )
                        chunks.append(chunk)
                    return b"".join(chunks)
            except httpx.TransportError as exc:
                raise ParserTransientError(
                    "MinerU archive download failed",
                    phase="download",
                    task_id=task_id,
                    exception_type=type(exc).__name__,
                ) from exc
        raise ParserSecurityError("MinerU archive redirect handling failed")

    async def download_archive(
        self,
        api_client: httpx.AsyncClient,
        batch_id: str,
        data_id: str,
        archive_url: str,
        *,
        deadline: float | None = None,
    ) -> bytes:
        lifecycle_deadline = (
            deadline
            if deadline is not None
            else time.monotonic() + self.config.task_timeout_seconds
        )
        current_url = archive_url
        attempt = 0
        last_error: ParserTransientError | None = None
        async with self._download_client() as download_client:
            while time.monotonic() < lifecycle_deadline:
                attempt += 1
                try:
                    return await self._download_once(
                        download_client,
                        current_url,
                        task_id=batch_id,
                    )
                except ParserTransientError as exc:
                    last_error = exc
                    logger.warning(
                        "MinerU archive download failed; refreshing its URL; "
                        "diagnostics=%s",
                        json.dumps(exc.diagnostic_fields(), sort_keys=True),
                        extra={
                            **exc.diagnostic_fields(),
                            "attempt": attempt,
                            "retry_mode": (
                                "slow" if attempt > FAST_RETRY_ATTEMPTS else "fast"
                            ),
                        },
                    )
                    await self._backoff(
                        attempt,
                        exc,
                        deadline=lifecycle_deadline,
                        slow_after_fast_failures=True,
                    )
                    if time.monotonic() >= lifecycle_deadline:
                        break
                    refreshed = await self._get_status_until_deadline(
                        api_client,
                        batch_id,
                        data_id=data_id,
                        deadline=lifecycle_deadline,
                    )
                    if str(refreshed.get("state", "")).lower() == "done":
                        refreshed_url = refreshed.get("full_zip_url")
                        if isinstance(refreshed_url, str) and refreshed_url:
                            current_url = refreshed_url
        if last_error is not None:
            raise ParserTransientError(
                f"MinerU batch {batch_id} archive download deadline expired",
                phase="download",
                task_id=batch_id,
                mineru_code=last_error.mineru_code,
                trace_id=last_error.trace_id,
                http_status=last_error.http_status,
                exception_type=last_error.exception_type,
            ) from last_error
        raise ParserTransientError(
            f"MinerU batch {batch_id} archive download deadline expired",
            phase="download",
            task_id=batch_id,
        )

    def read_archive(self, archive_bytes: bytes) -> ParsedDocument:
        if len(archive_bytes) > self.config.max_archive_bytes:
            raise ParserSecurityError("MinerU archive exceeds configured size limit")

        markdown_found = False
        content_list: list[dict] | None = None
        total_uncompressed = 0

        try:
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_ARCHIVE_ENTRIES:
                    raise ParserSecurityError("MinerU archive contains too many files")

                for info in entries:
                    path = PurePosixPath(info.filename)
                    file_type = (info.external_attr >> 16) & 0o170000
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or file_type == 0o120000
                    ):
                        raise ParserSecurityError("Unsafe path in MinerU archive")
                    if info.is_dir():
                        continue
                    total_uncompressed += info.file_size
                    if total_uncompressed > self.config.max_archive_bytes:
                        raise ParserSecurityError(
                            "MinerU archive expands beyond configured limit"
                        )
                    if (
                        info.compress_size > 0
                        and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
                    ):
                        raise ParserSecurityError(
                            "MinerU archive has an unsafe compression ratio"
                        )

                    name = path.name.lower()
                    if name in {"full.md", "auto.md"} or name.endswith(".md"):
                        markdown_found = True
                    if name == "content_list.json" or (
                        content_list is None and name.endswith("_content_list.json")
                    ):
                        parsed = json.loads(archive.read(info))
                        if not isinstance(parsed, list):
                            raise ParserContentError(
                                "MinerU content_list.json is not a list"
                            )
                        content_list = parsed
        except zipfile.BadZipFile as exc:
            raise ParserContentError(
                "MinerU result is not a valid ZIP archive"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParserContentError("MinerU result contains invalid JSON") from exc

        if not markdown_found or content_list is None:
            raise ParserContentError(
                "MinerU result is missing markdown or content_list.json"
            )

        markdown, page_offsets = canonical_markdown(content_list)
        if len(markdown.strip()) < MIN_EXTRACTED_TEXT_CHARACTERS:
            raise ParserContentError("MinerU returned insufficient paper content")
        return ParsedDocument(
            markdown=markdown,
            page_offset_map=page_offsets,
            backend=ParserBackend.MINERU,
            quality=ParserQuality.FULL,
            parser_version=f"mineru-v4/{self.config.model_version}",
            archive_bytes=archive_bytes,
        )

    async def parse_file(
        self,
        pdf_bytes: bytes,
        *,
        data_id: str,
        deadline: float | None = None,
        phase_callback: Callable[[str, str | None], None] | None = None,
    ) -> ParsedDocument:
        lifecycle_deadline = min(
            deadline if deadline is not None else float("inf"),
            time.monotonic() + self.config.task_timeout_seconds,
        )
        if lifecycle_deadline <= time.monotonic():
            raise ParserTransientError(
                "MinerU foreground parsing budget is exhausted",
                phase="deadline",
            )
        async with self._api_client() as client:
            if phase_callback is not None:
                phase_callback("submit", None)
            checkpoint = await self._get_or_create_batch(
                client,
                data_id=data_id,
            )
            batch_id = checkpoint.batch_id
            if not checkpoint.uploaded:
                if phase_callback is not None:
                    phase_callback("upload", batch_id)
                await self.upload_file(
                    checkpoint.upload_url,
                    pdf_bytes,
                    batch_id=batch_id,
                    deadline=lifecycle_deadline,
                )
                await self.state_store.mark_uploaded(data_id)
            if phase_callback is not None:
                phase_callback("poll", batch_id)
            archive_url = await self.poll_batch(
                client,
                batch_id,
                data_id=data_id,
                deadline=lifecycle_deadline,
            )
            if phase_callback is not None:
                phase_callback("download", batch_id)
            archive_bytes = await self.download_archive(
                client,
                batch_id,
                data_id,
                archive_url,
                deadline=lifecycle_deadline,
            )
        if phase_callback is not None:
            phase_callback("archive", batch_id)
        try:
            return self.read_archive(archive_bytes)
        except ParserError as exc:
            raise self._add_error_context(
                exc,
                phase="archive",
                task_id=batch_id,
            )

    async def close(self) -> None:
        await self.state_store.close()
