"""Redis-backed state for resumable MinerU tasks."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import asdict, dataclass
from typing import Awaitable, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.pdf.models import ParserConfigurationError, ParserTransientError

STATE_TTL_SECONDS = 24 * 60 * 60
SUBMIT_LOCK_TTL_SECONDS = 60
SUBMIT_LOCK_WAIT_SECONDS = 15
SUBMIT_LOCK_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class MinerUBatchCheckpoint:
    batch_id: str
    upload_url: str
    uploaded: bool = False


class RedisStateClient(Protocol):
    async def get(self, key: str) -> object: ...

    async def set(
        self,
        key: str,
        value: str,
        *,
        ex: int,
        nx: bool = False,
    ) -> object: ...

    async def delete(self, key: str) -> object: ...

    async def eval(self, script: str, count: int, key: str, token: str) -> object: ...

    async def aclose(self) -> None: ...


class ParserTaskState(Protocol):
    async def get_checkpoint(self, job_id: str) -> MinerUBatchCheckpoint | None: ...

    async def save_checkpoint(
        self,
        job_id: str,
        checkpoint: MinerUBatchCheckpoint,
    ) -> None: ...

    async def mark_uploaded(self, job_id: str) -> MinerUBatchCheckpoint: ...

    async def clear(self, job_id: str) -> None: ...

    async def acquire_submit_lock(self, job_id: str) -> str | None: ...

    async def wait_for_checkpoint(
        self,
        job_id: str,
    ) -> MinerUBatchCheckpoint | None: ...

    async def release_submit_lock(self, job_id: str, token: str) -> None: ...

    async def close(self) -> None: ...


def parser_state_redis_url() -> str:
    configured = os.getenv("PDF_PARSE_REDIS_URL") or os.getenv("CELERY_RESULT_BACKEND")
    if not configured:
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            raise ParserConfigurationError(
                "PDF_PARSE_REDIS_URL or CELERY_RESULT_BACKEND is required in production"
            )
        configured = "redis://127.0.0.1:56379/0"
    if not configured.startswith(("redis://", "rediss://")):
        raise ParserConfigurationError("PDF parser state requires a Redis URL")
    return configured


class ParserStateStore:
    def __init__(
        self,
        redis_url: str | None = None,
        *,
        redis_client: RedisStateClient | None = None,
    ) -> None:
        self._redis: RedisStateClient = redis_client or cast(
            RedisStateClient,
            Redis.from_url(
                redis_url or parser_state_redis_url(),
                decode_responses=True,
            ),
        )

    @staticmethod
    def _checkpoint_key(job_id: str) -> str:
        return f"scholens:pdf-parse:{job_id}"

    @staticmethod
    def _lock_key(job_id: str) -> str:
        return f"scholens:pdf-parse:{job_id}:submit-lock"

    async def get_checkpoint(self, job_id: str) -> MinerUBatchCheckpoint | None:
        try:
            value = await self._redis.get(self._checkpoint_key(job_id))
        except RedisError as exc:
            raise ParserTransientError("PDF parser state is unavailable") from exc
        if not value:
            return None
        try:
            payload = json.loads(str(value))
            return MinerUBatchCheckpoint(
                batch_id=str(payload["batch_id"]),
                upload_url=str(payload["upload_url"]),
                uploaded=bool(payload["uploaded"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ParserTransientError(
                "MinerU batch checkpoint is invalid",
                phase="checkpoint",
            ) from exc

    async def save_checkpoint(
        self,
        job_id: str,
        checkpoint: MinerUBatchCheckpoint,
    ) -> None:
        try:
            await self._redis.set(
                self._checkpoint_key(job_id),
                json.dumps(asdict(checkpoint), separators=(",", ":"), sort_keys=True),
                ex=STATE_TTL_SECONDS,
            )
        except RedisError as exc:
            raise ParserTransientError("Could not persist MinerU batch state") from exc

    async def mark_uploaded(self, job_id: str) -> MinerUBatchCheckpoint:
        checkpoint = await self.get_checkpoint(job_id)
        if checkpoint is None:
            raise ParserTransientError(
                "MinerU batch checkpoint is missing",
                phase="checkpoint",
            )
        uploaded = MinerUBatchCheckpoint(
            batch_id=checkpoint.batch_id,
            upload_url=checkpoint.upload_url,
            uploaded=True,
        )
        await self.save_checkpoint(job_id, uploaded)
        return uploaded

    async def clear(self, job_id: str) -> None:
        try:
            await self._redis.delete(self._checkpoint_key(job_id))
        except RedisError as exc:
            raise ParserTransientError("Could not clear MinerU batch state") from exc

    async def acquire_submit_lock(self, job_id: str) -> str | None:
        token = uuid.uuid4().hex
        try:
            acquired = await self._redis.set(
                self._lock_key(job_id),
                token,
                ex=SUBMIT_LOCK_TTL_SECONDS,
                nx=True,
            )
        except RedisError as exc:
            raise ParserTransientError("Could not acquire MinerU submit lock") from exc
        return token if acquired else None

    async def wait_for_checkpoint(
        self,
        job_id: str,
    ) -> MinerUBatchCheckpoint | None:
        deadline = asyncio.get_running_loop().time() + SUBMIT_LOCK_WAIT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            checkpoint = await self.get_checkpoint(job_id)
            if checkpoint is not None:
                return checkpoint
            await asyncio.sleep(SUBMIT_LOCK_POLL_SECONDS)
        return None

    async def release_submit_lock(self, job_id: str, token: str) -> None:
        script = """
        if redis.call("get", KEYS[1]) == ARGV[1] then
            return redis.call("del", KEYS[1])
        end
        return 0
        """
        try:
            await cast(
                Awaitable[object],
                self._redis.eval(script, 1, self._lock_key(job_id), token),
            )
        except RedisError as exc:
            raise ParserTransientError("Could not release MinerU submit lock") from exc

    async def close(self) -> None:
        await cast(Awaitable[None], self._redis.aclose())
