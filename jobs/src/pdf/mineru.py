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
from urllib.parse import urljoin, urlsplit

import httpx

from src.pdf.models import (
    ParsedDocument,
    ParserBackend,
    ParserConfigurationError,
    ParserContentError,
    ParserQuality,
    ParserSecurityError,
    ParserTransientError,
)
from src.pdf.state import ParserStateStore

logger = logging.getLogger(__name__)

MAX_NETWORK_ATTEMPTS = 4
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

        base_url = os.getenv(
            "MINERU_API_BASE_URL", "https://mineru.net/api/v4"
        ).rstrip("/")
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
        if min(
            poll_seconds,
            task_timeout_seconds,
            request_timeout_seconds,
            max_archive_bytes,
        ) <= 0:
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
        indexed.sort(
            key=lambda item: (int(item[1].get("page_idx", 0) or 0), item[0])
        )
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
        state_store: ParserStateStore | None = None,
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

    @classmethod
    def _classify_response(cls, response: httpx.Response, phase: str) -> None:
        if response.status_code in {401, 403}:
            raise ParserConfigurationError(f"MinerU authorization failed during {phase}")
        if response.status_code == 429 or response.status_code >= 500:
            raise ParserTransientError(
                f"MinerU is temporarily unavailable during {phase}",
                retry_after=cls._retry_after(response),
            )
        if response.status_code >= 400:
            raise ParserContentError(f"MinerU rejected the document during {phase}")

    @staticmethod
    def _classify_payload(payload: dict, phase: str) -> None:
        code = str(payload.get("code", "0"))
        if code in {"0", "None"}:
            return
        if code in CONFIGURATION_API_CODES:
            raise ParserConfigurationError(f"MinerU credentials failed during {phase}")
        if code in TRANSIENT_API_CODES:
            raise ParserTransientError(
                f"MinerU is temporarily unavailable during {phase}"
            )
        raise ParserContentError(f"MinerU rejected the document during {phase}")

    async def _json_request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        phase: str,
        json_body: dict | None = None,
    ) -> dict:
        try:
            response = await client.request(method, url, json=json_body)
        except httpx.TransportError as exc:
            raise ParserTransientError(
                f"MinerU network failure during {phase}"
            ) from exc
        self._classify_response(response, phase)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ParserTransientError(
                f"MinerU returned invalid JSON during {phase}"
            ) from exc
        if not isinstance(payload, dict):
            raise ParserTransientError(
                f"MinerU returned an invalid response during {phase}"
            )
        self._classify_payload(payload, phase)
        return payload

    async def submit_task(
        self,
        client: httpx.AsyncClient,
        source_url: str,
        *,
        data_id: str,
    ) -> str:
        payload = await self._json_request(
            client,
            "POST",
            f"{self.config.base_url}/extract/task",
            phase="submit",
            json_body={
                "url": source_url,
                "model_version": self.config.model_version,
                "is_ocr": True,
                "enable_formula": True,
                "enable_table": True,
                "data_id": data_id,
            },
        )
        task_id = (payload.get("data") or {}).get("task_id")
        if not task_id or not isinstance(task_id, str):
            raise ParserTransientError("MinerU response did not include task_id")
        return task_id

    async def _get_or_submit_task(
        self,
        client: httpx.AsyncClient,
        source_url: str,
        *,
        data_id: str,
    ) -> str:
        existing_task_id = await self.state_store.get_task_id(data_id)
        if existing_task_id:
            return existing_task_id

        lock_token = await self.state_store.acquire_submit_lock(data_id)
        if lock_token is None:
            existing_task_id = await self.state_store.wait_for_task_id(data_id)
            if existing_task_id:
                return existing_task_id
            raise ParserTransientError("Timed out waiting for MinerU task submission")

        try:
            existing_task_id = await self.state_store.get_task_id(data_id)
            if existing_task_id:
                return existing_task_id
            task_id = await self.submit_task(client, source_url, data_id=data_id)
            await self.state_store.save_task_id(data_id, task_id)
            return task_id
        finally:
            try:
                await self.state_store.release_submit_lock(data_id, lock_token)
            except ParserTransientError:
                logger.warning(
                    "Could not release MinerU submit lock for %s",
                    data_id,
                    exc_info=True,
                )

    async def get_task_status(
        self,
        client: httpx.AsyncClient,
        task_id: str,
    ) -> dict:
        payload = await self._json_request(
            client,
            "GET",
            f"{self.config.base_url}/extract/task/{task_id}",
            phase="poll",
        )
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise ParserTransientError("MinerU task status is invalid")
        return data

    @staticmethod
    async def _backoff(attempt: int, error: ParserTransientError) -> None:
        delay = (
            error.retry_after
            if error.retry_after is not None
            else min(8.0, 2 ** (attempt - 1)) + random.uniform(0, 0.25)
        )
        await asyncio.sleep(delay)

    async def _get_status_with_retry(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        *,
        deadline: float,
    ) -> dict:
        last_error: ParserTransientError | None = None
        for attempt in range(1, MAX_NETWORK_ATTEMPTS + 1):
            if time.monotonic() >= deadline:
                break
            try:
                return await self.get_task_status(client, task_id)
            except ParserTransientError as exc:
                last_error = exc
                if attempt == MAX_NETWORK_ATTEMPTS:
                    break
                await self._backoff(attempt, exc)
        raise last_error or ParserTransientError("MinerU polling timed out")

    async def poll_task(
        self,
        client: httpx.AsyncClient,
        task_id: str,
    ) -> str:
        deadline = time.monotonic() + self.config.task_timeout_seconds
        while time.monotonic() < deadline:
            data = await self._get_status_with_retry(
                client,
                task_id,
                deadline=deadline,
            )
            state = str(data.get("state", "")).lower()
            if state == "done":
                archive_url = data.get("full_zip_url")
                if not archive_url or not isinstance(archive_url, str):
                    raise ParserTransientError(
                        "MinerU completed without an archive URL"
                    )
                return archive_url
            if state == "failed":
                raise ParserContentError("MinerU could not parse the document")
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(min(self.config.poll_seconds, remaining))
        raise ParserTransientError(f"MinerU task {task_id} timed out")

    @staticmethod
    def _validate_archive_url(url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ParserSecurityError(
                "MinerU archive URL must be a public HTTPS URL"
            )
        try:
            addresses = socket.getaddrinfo(
                parsed.hostname,
                parsed.port or 443,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ParserTransientError(
                "MinerU archive host could not be resolved"
            ) from exc
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_global for address in addresses
        ):
            raise ParserSecurityError(
                "MinerU archive URL resolved to a non-public address"
            )

    async def _download_once(
        self,
        client: httpx.AsyncClient,
        initial_url: str,
    ) -> bytes:
        url = initial_url
        for redirect_count in range(MAX_ARCHIVE_REDIRECTS + 1):
            await asyncio.to_thread(self._validate_archive_url, url)
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
                        )
                    if response.status_code >= 400:
                        raise ParserTransientError(
                            "MinerU archive URL is unavailable"
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
                    "MinerU archive download failed"
                ) from exc
        raise ParserSecurityError("MinerU archive redirect handling failed")

    async def download_archive(
        self,
        api_client: httpx.AsyncClient,
        task_id: str,
        archive_url: str,
    ) -> bytes:
        current_url = archive_url
        async with self._download_client() as download_client:
            for attempt in range(1, MAX_NETWORK_ATTEMPTS + 1):
                try:
                    return await self._download_once(download_client, current_url)
                except ParserTransientError as exc:
                    if attempt == MAX_NETWORK_ATTEMPTS:
                        raise
                    await self._backoff(attempt, exc)
                    refreshed = await self._get_status_with_retry(
                        api_client,
                        task_id,
                        deadline=time.monotonic()
                        + self.config.request_timeout_seconds
                        * MAX_NETWORK_ATTEMPTS,
                    )
                    if str(refreshed.get("state", "")).lower() == "done":
                        refreshed_url = refreshed.get("full_zip_url")
                        if isinstance(refreshed_url, str) and refreshed_url:
                            current_url = refreshed_url
        raise ParserTransientError("MinerU archive download failed")

    def read_archive(self, archive_bytes: bytes) -> ParsedDocument:
        if len(archive_bytes) > self.config.max_archive_bytes:
            raise ParserSecurityError(
                "MinerU archive exceeds configured size limit"
            )

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
                    if path.is_absolute() or ".." in path.parts or file_type == 0o120000:
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
            raise ParserContentError("MinerU result is not a valid ZIP archive") from exc
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

    async def parse_url(self, source_url: str, *, data_id: str) -> ParsedDocument:
        async with self._api_client() as client:
            task_id = await self._get_or_submit_task(
                client,
                source_url,
                data_id=data_id,
            )
            archive_url = await self.poll_task(client, task_id)
            archive_bytes = await self.download_archive(
                client,
                task_id,
                archive_url,
            )
        return self.read_archive(archive_bytes)

    async def close(self) -> None:
        await self.state_store.close()
