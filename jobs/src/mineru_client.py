"""MinerU v4 asynchronous PDF parsing client."""

from __future__ import annotations

import asyncio
import io
import json
import os
import time
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

import httpx


@dataclass(frozen=True)
class MinerUResult:
    markdown: str
    content_list: list[dict]
    archive_bytes: bytes


class MinerUClient:
    def __init__(self) -> None:
        token = os.getenv("MINERU_API_TOKEN")
        if not token:
            raise ValueError("MINERU_API_TOKEN environment variable is not set")
        self.base_url = os.getenv(
            "MINERU_API_BASE_URL", "https://mineru.net/api/v4"
        ).rstrip("/")
        self.model_version = os.getenv("MINERU_MODEL_VERSION", "vlm")
        self.poll_seconds = float(os.getenv("MINERU_POLL_INTERVAL_SECONDS", "3"))
        self.timeout_seconds = float(os.getenv("MINERU_TASK_TIMEOUT_SECONDS", "600"))
        self.max_archive_bytes = int(
            os.getenv("MINERU_MAX_ARCHIVE_BYTES", str(256 * 1024 * 1024))
        )
        self.headers = {"Authorization": f"Bearer {token}"}

    async def parse_url(self, source_url: str, *, data_id: str) -> MinerUResult:
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=httpx.Timeout(60),
            follow_redirects=False,
        ) as client:
            response = await client.post(
                f"{self.base_url}/extract/task",
                json={
                    "url": source_url,
                    "model_version": self.model_version,
                    "is_ocr": True,
                    "enable_formula": True,
                    "enable_table": True,
                    "data_id": data_id,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (0, "0", None):
                raise RuntimeError(f"MinerU rejected task: {payload.get('msg')}")
            task_id = (payload.get("data") or {}).get("task_id")
            if not task_id:
                raise RuntimeError("MinerU response did not include task_id")

            deadline = time.monotonic() + self.timeout_seconds
            archive_url: str | None = None
            while time.monotonic() < deadline:
                status_response = await client.get(
                    f"{self.base_url}/extract/task/{task_id}"
                )
                status_response.raise_for_status()
                status_payload = status_response.json()
                data = status_payload.get("data") or {}
                state = str(data.get("state", "")).lower()
                if state == "done":
                    archive_url = data.get("full_zip_url")
                    break
                if state == "failed":
                    raise RuntimeError(
                        f"MinerU task failed: {data.get('err_msg') or 'unknown error'}"
                    )
                await asyncio.sleep(self.poll_seconds)

            if not archive_url:
                raise TimeoutError(f"MinerU task {task_id} timed out")

            archive_response = await client.get(archive_url)
            archive_response.raise_for_status()
            archive_bytes = archive_response.content

        return self._read_archive(archive_bytes)

    def _read_archive(self, archive_bytes: bytes) -> MinerUResult:
        if len(archive_bytes) > self.max_archive_bytes:
            raise ValueError("MinerU archive exceeds configured size limit")

        markdown: str | None = None
        content_list: list[dict] | None = None
        total_uncompressed = 0

        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            for info in archive.infolist():
                path = PurePosixPath(info.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or info.is_dir()
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    if info.is_dir():
                        continue
                    raise ValueError("Unsafe path in MinerU archive")
                total_uncompressed += info.file_size
                if total_uncompressed > self.max_archive_bytes:
                    raise ValueError("MinerU archive expands beyond configured limit")

                name = path.name.lower()
                if name in {"full.md", "auto.md"} or (
                    markdown is None and name.endswith(".md")
                ):
                    markdown = archive.read(info).decode("utf-8")
                if name == "content_list.json" or (
                    content_list is None and name.endswith("_content_list.json")
                ):
                    parsed = json.loads(archive.read(info))
                    if not isinstance(parsed, list):
                        raise ValueError("MinerU content_list.json is not a list")
                    content_list = parsed

        if markdown is None or content_list is None:
            raise ValueError("MinerU result is missing markdown or content_list.json")
        return MinerUResult(
            markdown=markdown,
            content_list=content_list,
            archive_bytes=archive_bytes,
        )


mineru_client = MinerUClient() if os.getenv("MINERU_API_TOKEN") else None
