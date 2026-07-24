from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_redis: Redis | None = None

_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) >= limit then
  return 0
end
redis.call('ZADD', key, expires, member)
redis.call('EXPIRE', key, math.ceil((expires - now) / 1000))
return 1
"""


class AILimitExceeded(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _redis_client() -> Redis | None:
    global _redis
    url = os.getenv("AI_LIMIT_REDIS_URL")
    if not url:
        return None
    if _redis is None:
        _redis = Redis.from_url(url, decode_responses=True)
    return _redis


async def enforce_rate_limit(
    *,
    user_id: int,
    ip_address: str,
    feature: str,
) -> None:
    client = _redis_client()
    if client is None:
        if os.getenv("ENVIRONMENT") == "production":
            raise RuntimeError("AI_LIMIT_REDIS_URL is required in production")
        return

    window_seconds = int(os.getenv("AI_RATE_WINDOW_SECONDS", "60"))
    user_limit = int(os.getenv("AI_RATE_PER_USER", "60"))
    ip_limit = int(os.getenv("AI_RATE_PER_IP", "120"))
    window = int(time.time()) // window_seconds
    keys = (
        (f"scholens:rate:user:{user_id}:{feature}:{window}", user_limit),
        (f"scholens:rate:ip:{ip_address}:{feature}:{window}", ip_limit),
    )
    try:
        async with client.pipeline(transaction=True) as pipe:
            for key, _ in keys:
                pipe.incr(key)
                pipe.expire(key, window_seconds + 1)
            values = await pipe.execute()
    except RedisError:
        logger.exception("Redis rate-limit check failed")
        raise AILimitExceeded("rate_limit_unavailable") from None

    counts = (int(values[0]), int(values[2]))
    if any(count > limit for count, (_, limit) in zip(counts, keys, strict=True)):
        raise AILimitExceeded("rate_limit_exceeded")


@dataclass(frozen=True)
class AIConcurrencyLease:
    key: str
    member: str


async def acquire_concurrency(
    *,
    user_id: int,
    category: str,
    operation_id: str | None = None,
) -> AIConcurrencyLease:
    client = _redis_client()
    member = operation_id or uuid.uuid4().hex
    key = f"scholens:concurrency:{category}:{user_id}"
    if client is None:
        if os.getenv("ENVIRONMENT") == "production":
            raise RuntimeError("AI_LIMIT_REDIS_URL is required in production")
        return AIConcurrencyLease(key="", member=member)

    limits = {
        "interactive": int(os.getenv("AI_MAX_INTERACTIVE_PER_USER", "8")),
        "background": int(os.getenv("AI_MAX_BACKGROUND_PER_USER", "4")),
        "audio": int(os.getenv("AI_MAX_AUDIO_PER_USER", "2")),
    }
    limit = limits[category]
    ttl_seconds = int(os.getenv("AI_CONCURRENCY_TTL_SECONDS", "7200"))
    now_ms = int(time.time() * 1000)
    try:
        acquired = await client.eval(
            _ACQUIRE_SCRIPT,
            1,
            key,
            now_ms,
            now_ms + ttl_seconds * 1000,
            limit,
            member,
        )
    except RedisError:
        logger.exception("Redis concurrency check failed")
        raise AILimitExceeded("concurrency_limit_unavailable") from None
    if not acquired:
        raise AILimitExceeded(f"{category}_concurrency_exceeded")
    return AIConcurrencyLease(key=key, member=member)


async def release_concurrency(lease: AIConcurrencyLease) -> None:
    client = _redis_client()
    if client is None or not lease.key:
        return
    try:
        await client.zrem(lease.key, lease.member)
    except RedisError:
        logger.exception("Failed to release AI concurrency lease")


async def release_concurrency_by_id(
    *, user_id: int, category: str, operation_id: str
) -> None:
    await release_concurrency(
        AIConcurrencyLease(
            key=f"scholens:concurrency:{category}:{user_id}",
            member=operation_id,
        )
    )
