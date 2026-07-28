"""DeepSeek narrative generation and MOSS Voice synthesis."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.llm_client import llm_client
from src.s3_service import s3_service
from src.schemas import AudioOverviewRequest, AudioOverviewResult


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


def _clean_for_speech(text: str) -> str:
    cleaned = re.sub(r"\s*\[\^[\d]+(?:,\s*\^[\d]+)*\]", "", text)
    cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)
    cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"(\*\*|__|~~|`)(.+?)\1", r"\2", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _audio_format(audio: bytes) -> tuple[str, str]:
    if len(audio) >= 12 and audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
        return "wav", "audio/wav"
    if audio.startswith(b"ID3") or (
        len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0
    ):
        return "mp3", "audio/mpeg"
    raise ValueError("moss_audio_format_invalid")


class MossVoiceClient:
    def __init__(self) -> None:
        api_key = os.getenv("MOSS_API_KEY")
        voice_id = os.getenv("MOSS_VOICE_ID")
        if not api_key or not voice_id:
            raise RuntimeError("moss_not_configured")
        self.base_url = os.getenv(
            "MOSS_API_BASE_URL",
            "https://api.mosi.cn/v1",
        ).rstrip("/")
        self.model = os.getenv("MOSS_TTS_MODEL", "moss-tts")
        self.voice_id = voice_id
        self.poll_seconds = float(os.getenv("MOSS_POLL_INTERVAL_SECONDS", "3"))
        self.timeout_seconds = float(os.getenv("MOSS_TASK_TIMEOUT_SECONDS", "600"))
        self.max_bytes = int(os.getenv("MOSS_MAX_AUDIO_BYTES", str(100 * 1024 * 1024)))
        self.headers = {"Authorization": f"Bearer {api_key}"}

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("moss_audio_url_invalid")
        addresses = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or 443,
            type=socket.SOCK_STREAM,
        )
        if not addresses or any(
            not ipaddress.ip_address(address[4][0]).is_global for address in addresses
        ):
            raise ValueError("moss_audio_url_not_public")

    def _download(self, url: str) -> bytes:
        self._validate_url(url)
        chunks: list[bytes] = []
        size = 0
        with httpx.Client(timeout=httpx.Timeout(60), follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise ValueError("moss_audio_redirect_rejected")
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > self.max_bytes:
                    raise ValueError("moss_audio_too_large")
                content_type = response.headers.get("content-type", "").lower()
                if content_type and not (
                    content_type.startswith("audio/")
                    or content_type.startswith("application/octet-stream")
                ):
                    raise ValueError("moss_audio_content_type_invalid")
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ValueError("moss_audio_too_large")
                    chunks.append(chunk)
        return b"".join(chunks)

    def synthesize(self, text: str) -> tuple[bytes, str, str]:
        narration = _clean_for_speech(text)
        if not narration:
            raise ValueError("moss_narration_empty")
        with httpx.Client(
            headers=self.headers,
            timeout=httpx.Timeout(60),
            follow_redirects=False,
        ) as client:
            response = client.post(
                f"{self.base_url}/audio/speech",
                json={
                    "model": self.model,
                    "input": narration,
                    "voice_id": self.voice_id,
                    "response_format": "mp3",
                    "delivery_method": "url",
                    "async": True,
                },
            )
            response.raise_for_status()
            task_id = _find_value(response.json(), {"task_id", "taskId"})
            if not task_id:
                raise RuntimeError("moss_task_id_missing")

            deadline = time.monotonic() + self.timeout_seconds
            audio_url: str | None = None
            while time.monotonic() < deadline:
                status_response = client.get(f"{self.base_url}/audio/tasks/{task_id}")
                status_response.raise_for_status()
                payload = status_response.json()
                state = (_find_value(payload, {"status", "state"}) or "").lower()
                if state in {"failed", "failure", "error"}:
                    raise RuntimeError("moss_synthesis_failed")
                audio_url = _find_value(
                    payload,
                    {"url", "audio_url", "audioUrl", "result_url"},
                )
                if audio_url and state in {"completed", "succeeded", "success", "done"}:
                    break
                time.sleep(self.poll_seconds)
        if not audio_url:
            raise TimeoutError("moss_synthesis_timeout")
        audio = self._download(audio_url)
        extension, content_type = _audio_format(audio)
        return audio, extension, content_type


async def generate_audio(request: AudioOverviewRequest) -> AudioOverviewResult:
    contents = [
        (
            source.id,
            source.title,
            s3_service.download_file_to_bytes(source.canonical_s3_key).decode(
                "utf-8",
                errors="replace",
            ),
        )
        for source in request.documents
    ]
    narrative = await llm_client.create_audio_narrative(
        request=request,
        document_contents=contents,
    )
    moss = MossVoiceClient()
    audio, extension, content_type = moss.synthesize(narrative.transcript)
    object_key = f"research/audio/{request.research_item_id}.{extension}"
    s3_service.upload_bytes_to_key(audio, object_key, content_type)
    return AudioOverviewResult(
        research_item_id=request.research_item_id,
        title=narrative.title,
        transcript=narrative.transcript,
        citations=narrative.citations,
        s3_object_key=object_key,
        voice_id=moss.voice_id,
        model_version=moss.model,
    )
