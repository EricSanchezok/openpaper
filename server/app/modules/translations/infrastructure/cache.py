"""Compact Redis cache for completed translations."""

from __future__ import annotations

import json
import logging
import secrets

from app.modules.translations.application import TranslationCacheValue
from app.modules.translations.domain import (
    normalize_language_tag,
    validate_translated_text,
)
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

TRANSLATION_CACHE_TTL_SECONDS = 3_600
TRANSLATION_LEASE_TTL_SECONDS = 150
MAX_CACHE_VALUE_BYTES = 65_536
REDIS_CONNECT_TIMEOUT_SECONDS = 1.0
REDIS_OPERATION_TIMEOUT_SECONDS = 1.0

_RELEASE_LEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisTranslationCache:
    def __init__(self, url: str | None) -> None:
        self._client = (
            Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=REDIS_CONNECT_TIMEOUT_SECONDS,
                socket_timeout=REDIS_OPERATION_TIMEOUT_SECONDS,
                retry_on_timeout=False,
            )
            if url is not None
            else None
        )

    async def get(self, key: str) -> TranslationCacheValue | None:
        if self._client is None:
            return None
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("cache_value_not_object")
            translated_value = payload["translated_text"]
            target_value = payload["target_language"]
            if not isinstance(translated_value, str) or not isinstance(
                target_value, str
            ):
                raise ValueError("cache_value_types_invalid")
            translated_text = validate_translated_text(translated_value)
            target_language = normalize_language_tag(target_value)
            return TranslationCacheValue(
                translated_text=translated_text,
                target_language=target_language,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("translation.cache.invalid_value")
            await self._delete(key)
            return None
        except RedisError:
            logger.exception("translation.cache.lookup_failed")
            return None

    async def set(self, key: str, value: TranslationCacheValue) -> None:
        if self._client is None:
            return
        raw = json.dumps(
            {
                "translated_text": value.translated_text,
                "target_language": value.target_language,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(raw.encode()) > MAX_CACHE_VALUE_BYTES:
            logger.warning("translation.cache.value_too_large")
            return
        try:
            await self._client.set(
                key,
                raw,
                ex=TRANSLATION_CACHE_TTL_SECONDS,
            )
        except RedisError:
            logger.exception("translation.cache.write_failed")

    async def acquire(self, key: str) -> str | None:
        token = secrets.token_urlsafe(24)
        if self._client is None:
            return token
        try:
            acquired = await self._client.set(
                self._lease_key(key),
                token,
                nx=True,
                ex=TRANSLATION_LEASE_TTL_SECONDS,
            )
            return token if acquired else None
        except RedisError:
            logger.exception("translation.cache.lease_acquire_failed")
            return token

    async def release(self, key: str, lease_token: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.eval(
                _RELEASE_LEASE_SCRIPT,
                1,
                self._lease_key(key),
                lease_token,
            )
        except RedisError:
            logger.exception("translation.cache.lease_release_failed")

    async def _delete(self, key: str) -> None:
        if self._client is None:
            return
        try:
            await self._client.delete(key)
        except RedisError:
            logger.exception("translation.cache.invalid_value_delete_failed")

    @staticmethod
    def _lease_key(key: str) -> str:
        return f"{key}:lease"
