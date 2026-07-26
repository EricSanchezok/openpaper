"""Redis-backed state for resumable MinerU tasks."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Awaitable, Protocol, cast

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.pdf.models import ParserConfigurationError, ParserTransientError

STATE_TTL_SECONDS = 24 * 60 * 60
SUBMIT_LOCK_TTL_SECONDS = 60
SUBMIT_LOCK_WAIT_SECONDS = 15
SUBMIT_LOCK_POLL_SECONDS = 0.25


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
    async def get_task_id(self, job_id: str) -> str | None: ...

    async def save_task_id(self, job_id: str, task_id: str) -> None: ...

    async def clear(self, job_id: str) -> None: ...

    async def acquire_submit_lock(self, job_id: str) -> str | None: ...

    async def wait_for_task_id(self, job_id: str) -> str | None: ...

    async def release_submit_lock(self, job_id: str, token: str) -> None: ...

    async def close(self) -> None: ...


def parser_state_redis_url() -> str:
    configured = os.getenv("PDF_PARSE_REDIS_URL") or os.getenv("CELERY_RESULT_BACKEND")
    if not configured:
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            raise ParserConfigurationError(
                "PDF_PARSE_REDIS_URL or CELERY_RESULT_BACKEND is required in production"
            )
        configured = "redis://localhost:6379/0"
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
    def _task_key(job_id: str) -> str:
        return f"scholens:pdf-parse:{job_id}"

    @staticmethod
    def _lock_key(job_id: str) -> str:
        return f"scholens:pdf-parse:{job_id}:submit-lock"

    async def get_task_id(self, job_id: str) -> str | None:
        try:
            value = await self._redis.get(self._task_key(job_id))
        except RedisError as exc:
            raise ParserTransientError("PDF parser state is unavailable") from exc
        return str(value) if value else None

    async def save_task_id(self, job_id: str, task_id: str) -> None:
        try:
            await self._redis.set(
                self._task_key(job_id),
                task_id,
                ex=STATE_TTL_SECONDS,
            )
        except RedisError as exc:
            raise ParserTransientError("Could not persist MinerU task state") from exc

    async def clear(self, job_id: str) -> None:
        try:
            await self._redis.delete(self._task_key(job_id))
        except RedisError as exc:
            raise ParserTransientError("Could not clear MinerU task state") from exc

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

    async def wait_for_task_id(self, job_id: str) -> str | None:
        deadline = asyncio.get_running_loop().time() + SUBMIT_LOCK_WAIT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            task_id = await self.get_task_id(job_id)
            if task_id:
                return task_id
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
