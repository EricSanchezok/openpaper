"""MOSS Voice text-to-speech adapter."""

from __future__ import annotations

import os
import re
import tempfile
import time
from typing import Any

import httpx

from app.helpers.s3 import s3_service


def clean_markdown_for_speech(text: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"(\*\*|__|~~|`)(.+?)\1", r"\2", cleaned)
    cleaned = re.sub(r"^>\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^[*\-+]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\d+\.\s+", "", cleaned, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _find_value(payload: Any, keys: set[str]) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and isinstance(value, str) and value:
                return value
        for value in payload.values():
            found = _find_value(value, keys)
            if found:
                return found
    return None


class MossSpeaker:
    def __init__(self) -> None:
        api_key = os.getenv("MOSS_API_KEY")
        voice_id = os.getenv("MOSS_VOICE_ID")
        if not api_key:
            raise ValueError("MOSS_API_KEY environment variable is required")
        if not voice_id:
            raise ValueError("MOSS_VOICE_ID environment variable is required")

        self.base_url = os.getenv(
            "MOSS_API_BASE_URL", "https://api.mosi.cn/v1"
        ).rstrip("/")
        self.model = os.getenv("MOSS_TTS_MODEL", "moss-tts")
        self.voice_id = voice_id
        self.poll_seconds = float(os.getenv("MOSS_POLL_INTERVAL_SECONDS", "3"))
        self.timeout_seconds = float(os.getenv("MOSS_TASK_TIMEOUT_SECONDS", "600"))
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def generate_speech_from_text(self, *, title: str, text: str) -> tuple[str, str]:
        cleaned = clean_markdown_for_speech(text)
        if not cleaned:
            raise ValueError("Cannot synthesize empty narration")

        with httpx.Client(
            headers=self.headers,
            timeout=httpx.Timeout(60),
            follow_redirects=False,
        ) as client:
            response = client.post(
                f"{self.base_url}/audio/speech",
                json={
                    "model": self.model,
                    "input": cleaned,
                    "voice_id": self.voice_id,
                    "response_format": "mp3",
                    "delivery_method": "url",
                    "async": True,
                },
            )
            response.raise_for_status()
            payload = response.json()
            task_id = _find_value(payload, {"task_id", "taskId"})
            if not task_id:
                raise RuntimeError("MOSS response did not include task_id")

            deadline = time.monotonic() + self.timeout_seconds
            audio_url: str | None = None
            while time.monotonic() < deadline:
                task_response = client.get(
                    f"{self.base_url}/audio/tasks/{task_id}"
                )
                task_response.raise_for_status()
                task_payload = task_response.json()
                state = (
                    _find_value(task_payload, {"status", "state"}) or ""
                ).lower()
                if state in {"failed", "failure", "error"}:
                    raise RuntimeError("MOSS speech task failed")
                audio_url = _find_value(
                    task_payload,
                    {"url", "audio_url", "audioUrl", "result_url"},
                )
                if audio_url and state in {"completed", "succeeded", "success", "done"}:
                    break
                time.sleep(self.poll_seconds)

            if not audio_url:
                raise TimeoutError(f"MOSS speech task {task_id} timed out")

            audio_response = client.get(audio_url)
            audio_response.raise_for_status()
            audio_bytes = audio_response.content
            if not audio_bytes:
                raise ValueError("MOSS returned empty audio")

        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title or "audio")
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as output:
                output.write(audio_bytes)
                temp_path = output.name
            return s3_service.upload_any_file(
                file_path=temp_path,
                original_filename=f"{safe_title}.mp3",
                content_type="audio/mpeg",
            )
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)


speaker = (
    MossSpeaker()
    if os.getenv("MOSS_API_KEY") and os.getenv("MOSS_VOICE_ID")
    else None
)
