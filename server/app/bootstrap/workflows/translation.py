"""Short-transaction, cache-aside streaming translation workflow."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.llm.token_credits import llm_usage_context
from app.modules.translations.application import (
    PreparedTranslation,
    TranslationCache,
    TranslationCacheValue,
    TranslationCapacity,
    TranslationCapacityLease,
    TranslationRequest,
    TranslationStreamEvent,
    TranslationStreamProvider,
    TranslationStreamSpec,
)
from app.modules.translations.domain import (
    MAX_TRANSLATED_TEXT_CHARS,
    TranslationCacheIdentity,
    translation_cache_key,
    translation_instructions_hash,
    validate_translated_text,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext

logger = logging.getLogger(__name__)

TRANSLATION_CACHE_SCHEMA_REVISION = "translation-cache-v1"
SINGLE_FLIGHT_WAIT_ATTEMPTS = 20
SINGLE_FLIGHT_WAIT_SECONDS = 0.1


class TranslationWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        cache: TranslationCache,
        provider: TranslationStreamProvider,
        capacity: TranslationCapacity,
    ) -> None:
        self._executor = executor
        self._cache = cache
        self._provider = provider
        self._capacity = capacity

    async def open_stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: TranslationRequest,
        client_ip: str,
    ) -> AsyncIterator[TranslationStreamEvent]:
        prepared = self._executor.query(
            lambda capabilities: _prepare_translation(
                capabilities=capabilities,
                actor=actor,
                document_id=document_id,
                request=request,
            )
        )
        await self._capacity.enforce_rate(
            user_id=actor.id,
            client_ip=client_ip,
        )
        cache_key = translation_cache_key(
            TranslationCacheIdentity(
                schema_revision=TRANSLATION_CACHE_SCHEMA_REVISION,
                prompt_revision=self._provider.prompt_revision(),
                model_revision=self._provider.model_revision(),
                document_id=prepared.document_id,
                source_text=prepared.source_text,
                target_language=prepared.target_language,
                custom_instructions_hash=translation_instructions_hash(
                    prepared.custom_instructions
                ),
            )
        )
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return _cached_stream(cached)

        lease_token = await self._cache.acquire(cache_key)
        if lease_token is None:
            for _ in range(SINGLE_FLIGHT_WAIT_ATTEMPTS):
                await asyncio.sleep(SINGLE_FLIGHT_WAIT_SECONDS)
                cached = await self._cache.get(cache_key)
                if cached is not None:
                    return _cached_stream(cached)

        try:
            self._executor.query(
                lambda capabilities: capabilities.translations.require_token_credits(
                    actor=actor
                )
            )
            capacity_lease = await self._capacity.acquire(
                user_id=actor.id,
                operation_id=operation.trace.operation_id,
            )
        except BaseException:
            if lease_token is not None:
                await self._cache.release(cache_key, lease_token)
            raise

        return self._provider_stream(
            actor=actor,
            operation=operation,
            prepared=prepared,
            cache_key=cache_key,
            cache_lease_token=lease_token,
            capacity_lease=capacity_lease,
        )

    async def _provider_stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedTranslation,
        cache_key: str,
        cache_lease_token: str | None,
        capacity_lease: TranslationCapacityLease,
    ) -> AsyncIterator[TranslationStreamEvent]:
        chunks: list[str] = []
        translated_chars = 0
        yield TranslationStreamEvent(
            event="start",
            data={
                "target_language": prepared.target_language,
                "cache_hit": False,
            },
        )
        try:
            with llm_usage_context(
                user_id=actor.id,
                feature="translation",
                operation_id=str(operation.trace.operation_id),
            ):
                async for chunk in self._provider.stream(
                    TranslationStreamSpec(
                        paper_title=prepared.paper_title,
                        source_text=prepared.source_text,
                        target_language=prepared.target_language,
                        custom_instructions=prepared.custom_instructions,
                    )
                ):
                    chunks.append(chunk)
                    translated_chars += len(chunk)
                    if translated_chars > MAX_TRANSLATED_TEXT_CHARS:
                        raise ValueError("translated_text_too_long")
                    yield TranslationStreamEvent(
                        event="delta",
                        data={"text": chunk},
                    )
            translated_text = validate_translated_text("".join(chunks))
            await self._cache.set(
                cache_key,
                TranslationCacheValue(
                    translated_text=translated_text,
                    target_language=prepared.target_language,
                ),
            )
            yield TranslationStreamEvent(
                event="complete",
                data={"cache_hit": False},
            )
        except Exception:
            logger.exception(
                "Translation stream failed",
                extra={
                    "document_id": str(prepared.document_id),
                    "operation_id": str(operation.trace.operation_id),
                },
            )
            yield TranslationStreamEvent(
                event="error",
                data={
                    "code": "translation_unavailable",
                    "message": "Translation is temporarily unavailable",
                },
            )
        finally:
            await self._capacity.release(capacity_lease)
            if cache_lease_token is not None:
                await self._cache.release(cache_key, cache_lease_token)


def _prepare_translation(
    *,
    capabilities: ApplicationCapabilities,
    actor: Actor,
    document_id: UUID,
    request: TranslationRequest,
) -> PreparedTranslation:
    paper = capabilities.paper_details(
        actor=actor,
        document_id=document_id,
    )
    return capabilities.translations.prepare(
        actor=actor,
        document_id=document_id,
        paper_title=paper.title,
        request=request,
    )


async def _cached_stream(
    value: TranslationCacheValue,
) -> AsyncIterator[TranslationStreamEvent]:
    yield TranslationStreamEvent(
        event="start",
        data={
            "target_language": value.target_language,
            "cache_hit": True,
        },
    )
    yield TranslationStreamEvent(
        event="delta",
        data={"text": value.translated_text},
    )
    yield TranslationStreamEvent(
        event="complete",
        data={"cache_hit": True},
    )
