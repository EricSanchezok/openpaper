from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import suppress
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.bootstrap.workflows.translation import TranslationWorkflow
from app.llm.streaming import iterate_in_thread
from app.llm.token_credits import current_usage_context
from app.main import app
from app.modules.translations.application import (
    PreparedTranslation,
    TranslationCacheValue,
    TranslationCapacityLease,
    TranslationPreferencesRecord,
    TranslationPreferencesUpdateRequest,
    TranslationRequest,
    TranslationStreamEvent,
    TranslationStreamFailure,
    TranslationStreamFailureKind,
    TranslationStreamSpec,
    Translations,
)
from app.modules.translations.domain import (
    TranslationCacheIdentity,
    normalize_language_tag,
    normalize_source_text,
    translation_cache_key,
    translation_instructions_hash,
    translation_paper_title_hash,
)
from app.modules.translations.infrastructure.cache import RedisTranslationCache
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind
from app.transport.http.public_v1.translations import _sse


def _actor(*, user_id: int = 42, locale: str | None = "en-US") -> Actor:
    return Actor(
        id=user_id,
        email="reader@example.com",
        status="active",
        email_verified=True,
        locale=locale,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(request=RequestReference(request_id=uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


class _PreferencesGateway:
    def __init__(self) -> None:
        self.record: TranslationPreferencesRecord | None = None

    def get(self, *, user_id: int) -> TranslationPreferencesRecord | None:
        assert user_id == 42
        return self.record

    def upsert(
        self,
        *,
        user_id: int,
        preferences: TranslationPreferencesRecord,
    ) -> TranslationPreferencesRecord:
        assert user_id == 42
        self.record = preferences
        return preferences



class _Entitlements:
    def __init__(self) -> None:
        self.has_credits = True

    def has_token_credits(self, *, actor: Actor) -> bool:
        assert actor.id == 42
        return self.has_credits


class _Journal:
    def __init__(self) -> None:
        self.appended: list[dict[str, object]] = []

    def append(self, **kwargs: object) -> object:
        self.appended.append(kwargs)
        return object()


def test_translation_preferences_default_and_update_are_normalized() -> None:
    gateway = _PreferencesGateway()
    journal = _Journal()
    translations = Translations(
        gateway=gateway,
        entitlements=_Entitlements(),
        journal=cast(Any, journal),
    )

    defaults = translations.preferences(actor=_actor(locale="de-DE"))
    assert defaults.target_language == "de-DE"
    assert defaults.custom_instructions is None
    assert defaults.auto_translate_selection is True

    updated = translations.update_preferences(
        actor=_actor(),
        operation=_operation(),
        request=TranslationPreferencesUpdateRequest(
            target_language="EN-us",
            custom_instructions="  Preserve English terms.  ",
            auto_translate_selection=False,
        ),
    )
    assert updated.target_language == "en-US"
    assert updated.custom_instructions == "Preserve English terms."
    assert updated.auto_translate_selection is False
    assert len(journal.appended) == 1
    assert "Preserve English terms." not in repr(journal.appended[0])


def test_translation_preferences_reject_invalid_language() -> None:
    translations = Translations(
        gateway=_PreferencesGateway(),
        entitlements=_Entitlements(),
        journal=cast(Any, _Journal()),
    )
    with pytest.raises(AppError) as error:
        translations.update_preferences(
            actor=_actor(),
            operation=_operation(),
            request=TranslationPreferencesUpdateRequest(
                target_language="not_a_language",
                custom_instructions=None,
                auto_translate_selection=True,
            ),
        )
    assert error.value.code == "translation_language_invalid"


def test_translation_business_limits_use_stable_application_errors() -> None:
    translations = Translations(
        gateway=_PreferencesGateway(),
        entitlements=_Entitlements(),
        journal=cast(Any, _Journal()),
    )
    with pytest.raises(AppError) as text_error:
        translations.prepare(
            actor=_actor(),
            document_id=uuid4(),
            paper_title=None,
            request=TranslationRequest(text=" " * 10),
        )
    assert text_error.value.code == "translation_text_invalid"

    with pytest.raises(AppError) as instructions_error:
        translations.update_preferences(
            actor=_actor(),
            operation=_operation(),
            request=TranslationPreferencesUpdateRequest(
                target_language="zh-CN",
                custom_instructions="x" * 2_001,
                auto_translate_selection=True,
            ),
        )
    assert instructions_error.value.code == "translation_instructions_invalid"


def test_translation_normalization_and_cache_identity_are_deterministic() -> None:
    assert normalize_language_tag("ZH-hans-cn") == "zh-Hans-CN"
    assert normalize_source_text("  Retrieval-\r\naugmented   generation\n\n Works. ") == (
        "Retrieval-augmented generation\n\nWorks."
    )
    document_id = uuid4()
    identity = TranslationCacheIdentity(
        schema_revision="v1",
        prompt_revision="p1",
        model_revision="m1",
        document_id=document_id,
        paper_title_hash=translation_paper_title_hash("Paper title"),
        source_text="source",
        target_language="zh-CN",
        custom_instructions_hash=translation_instructions_hash(None),
    )
    assert translation_cache_key(identity) == translation_cache_key(identity)
    assert "source" not in translation_cache_key(identity)
    changed_title = TranslationCacheIdentity(
        schema_revision=identity.schema_revision,
        prompt_revision=identity.prompt_revision,
        model_revision=identity.model_revision,
        document_id=identity.document_id,
        paper_title_hash=translation_paper_title_hash("Updated title"),
        source_text=identity.source_text,
        target_language=identity.target_language,
        custom_instructions_hash=identity.custom_instructions_hash,
    )
    assert translation_cache_key(identity) != translation_cache_key(changed_title)


class _Cache:
    def __init__(self, value: TranslationCacheValue | None = None) -> None:
        self.value = value
        self.set_values: list[TranslationCacheValue] = []
        self.released: list[tuple[str, str]] = []
        self.get_calls = 0

    async def get(self, key: str) -> TranslationCacheValue | None:
        self.get_calls += 1
        return self.value

    async def set(self, key: str, value: TranslationCacheValue) -> None:
        self.value = value
        self.set_values.append(value)

    async def acquire(self, key: str) -> str | None:
        return "lease-token"

    async def release(self, key: str, lease_token: str) -> None:
        self.released.append((key, lease_token))


class _Provider:
    def __init__(self, chunks: tuple[str, ...] = ("译", "文")) -> None:
        self.chunks = chunks
        self.calls: list[TranslationStreamSpec] = []
        self.usage_feature: str | None = None

    def prompt_revision(self) -> str:
        return "prompt-v1"

    def model_revision(self) -> str:
        return "model-v1"

    async def stream(self, spec: TranslationStreamSpec) -> AsyncIterator[str]:
        self.calls.append(spec)
        usage = current_usage_context()
        self.usage_feature = usage.feature if usage is not None else None
        for chunk in self.chunks:
            yield chunk


class _FailingProvider(_Provider):
    def __init__(self, kind: TranslationStreamFailureKind) -> None:
        super().__init__(())
        self.kind = kind

    async def stream(self, spec: TranslationStreamSpec) -> AsyncIterator[str]:
        if False:
            yield ""
        raise TranslationStreamFailure(self.kind)


class _Capacity:
    def __init__(self) -> None:
        self.rate_checks = 0
        self.acquisitions = 0
        self.releases = 0

    async def enforce_rate(self, *, user_id: int, client_ip: str) -> None:
        self.rate_checks += 1

    async def acquire(
        self,
        *,
        user_id: int,
        operation_id: UUID,
    ) -> TranslationCapacityLease:
        self.acquisitions += 1
        return TranslationCapacityLease(key="capacity", member=str(operation_id))

    async def release(self, lease: TranslationCapacityLease) -> None:
        self.releases += 1


class _Translations:
    def __init__(self) -> None:
        self.token_checks = 0

    def prepare(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        paper_title: str | None,
        request: TranslationRequest,
    ) -> PreparedTranslation:
        return PreparedTranslation(
            document_id=document_id,
            paper_title=paper_title,
            source_text=request.text,
            target_language="zh-CN",
            custom_instructions=None,
        )

    def require_token_credits(self, *, actor: Actor) -> None:
        self.token_checks += 1


class _Capabilities:
    def __init__(self) -> None:
        self.translations = _Translations()

    def paper_details(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> object:
        return SimpleNamespace(title="Paper title")


class _DeniedCapabilities(_Capabilities):
    def paper_details(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> object:
        raise AppError(
            code="paper_not_found",
            message="Paper not found",
            kind=FailureKind.NOT_FOUND,
        )


class _Executor:
    def __init__(self, capabilities: _Capabilities) -> None:
        self.capabilities = capabilities

    def query(self, operation: Callable[[object], Any]) -> Any:
        return operation(self.capabilities)

    def command(self, operation: Callable[[object], Any]) -> Any:
        return operation(self.capabilities)

    async def command_async(self, operation: Callable[[object], Any]) -> Any:
        return await operation(self.capabilities)


async def _events(
    stream: AsyncIterator[TranslationStreamEvent],
) -> list[TranslationStreamEvent]:
    return [event async for event in stream]


@pytest.mark.asyncio
async def test_cached_translation_skips_provider_quota_and_concurrency() -> None:
    capabilities = _Capabilities()
    cache = _Cache(
        TranslationCacheValue(
            translated_text="缓存译文",
            target_language="zh-CN",
        )
    )
    provider = _Provider()
    capacity = _Capacity()
    workflow = TranslationWorkflow(
        executor=cast(Any, _Executor(capabilities)),
        cache=cache,
        provider=provider,
        capacity=capacity,
    )

    stream = await workflow.open_stream(
        actor=_actor(),
        operation=_operation(),
        document_id=uuid4(),
        request=TranslationRequest(text="source"),
        client_ip="127.0.0.1",
    )
    events = await _events(stream)

    assert [event.event for event in events] == ["start", "delta", "complete"]
    assert events[0].data["cache_hit"] is True
    assert provider.calls == []
    assert capabilities.translations.token_checks == 0
    assert capacity.acquisitions == 0


@pytest.mark.asyncio
async def test_paper_access_is_checked_before_cache_lookup() -> None:
    cache = _Cache(
        TranslationCacheValue(
            translated_text="must not leak",
            target_language="zh-CN",
        )
    )
    workflow = TranslationWorkflow(
        executor=cast(Any, _Executor(_DeniedCapabilities())),
        cache=cache,
        provider=_Provider(),
        capacity=_Capacity(),
    )

    with pytest.raises(AppError) as error:
        await workflow.open_stream(
            actor=_actor(),
            operation=_operation(),
            document_id=uuid4(),
            request=TranslationRequest(text="source"),
            client_ip="127.0.0.1",
        )

    assert error.value.code == "paper_not_found"
    assert cache.get_calls == 0


@pytest.mark.asyncio
async def test_streaming_translation_uses_shared_usage_context_and_caches_completion() -> None:
    capabilities = _Capabilities()
    cache = _Cache()
    provider = _Provider()
    capacity = _Capacity()
    workflow = TranslationWorkflow(
        executor=cast(Any, _Executor(capabilities)),
        cache=cache,
        provider=provider,
        capacity=capacity,
    )

    stream = await workflow.open_stream(
        actor=_actor(),
        operation=_operation(),
        document_id=uuid4(),
        request=TranslationRequest(text="source"),
        client_ip="127.0.0.1",
    )
    events = await _events(stream)

    assert [event.event for event in events] == [
        "start",
        "delta",
        "delta",
        "complete",
    ]
    assert provider.usage_feature == "translation"
    assert capabilities.translations.token_checks == 1
    assert cache.set_values[0].translated_text == "译文"
    assert capacity.releases == 1
    assert len(cache.released) == 1


@pytest.mark.asyncio
async def test_authorized_users_share_the_same_completed_translation_cache() -> None:
    cache = _Cache()
    provider = _Provider()
    workflow = TranslationWorkflow(
        executor=cast(Any, _Executor(_Capabilities())),
        cache=cache,
        provider=provider,
        capacity=_Capacity(),
    )
    document_id = uuid4()

    first = await workflow.open_stream(
        actor=_actor(user_id=42),
        operation=_operation(),
        document_id=document_id,
        request=TranslationRequest(text="source"),
        client_ip="127.0.0.1",
    )
    await _events(first)
    second = await workflow.open_stream(
        actor=_actor(user_id=43),
        operation=_operation(),
        document_id=document_id,
        request=TranslationRequest(text="source"),
        client_ip="127.0.0.2",
    )
    second_events = await _events(second)

    assert len(provider.calls) == 1
    assert second_events[0].data["cache_hit"] is True


@pytest.mark.asyncio
async def test_cancelled_translation_releases_capacity_without_caching_partial_text() -> None:
    capabilities = _Capabilities()
    cache = _Cache()
    capacity = _Capacity()
    workflow = TranslationWorkflow(
        executor=cast(Any, _Executor(capabilities)),
        cache=cache,
        provider=_Provider(chunks=("partial", "unused")),
        capacity=capacity,
    )
    stream = await workflow.open_stream(
        actor=_actor(),
        operation=_operation(),
        document_id=uuid4(),
        request=TranslationRequest(text="source"),
        client_ip="127.0.0.1",
    )

    assert (await anext(stream)).event == "start"
    assert (await anext(stream)).event == "delta"
    await cast(AsyncGenerator[TranslationStreamEvent, None], stream).aclose()

    assert cache.set_values == []
    assert capacity.releases == 1
    assert len(cache.released) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        (
            TranslationStreamFailureKind.PROVIDER_UNAVAILABLE,
            "translation_provider_unavailable",
        ),
        (
            TranslationStreamFailureKind.USAGE_SETTLEMENT_FAILED,
            "translation_usage_settlement_failed",
        ),
        (
            TranslationStreamFailureKind.INTERRUPTED,
            "translation_stream_interrupted",
        ),
    ],
)
async def test_stream_failures_preserve_semantic_error_codes(
    kind: TranslationStreamFailureKind,
    expected_code: str,
) -> None:
    workflow = TranslationWorkflow(
        executor=cast(Any, _Executor(_Capabilities())),
        cache=_Cache(),
        provider=_FailingProvider(kind),
        capacity=_Capacity(),
    )
    stream = await workflow.open_stream(
        actor=_actor(),
        operation=_operation(),
        document_id=uuid4(),
        request=TranslationRequest(text="source"),
        client_ip="127.0.0.1",
    )

    events = await _events(stream)

    assert [event.event for event in events] == ["start", "error"]
    assert events[-1].data["code"] == expected_code


@pytest.mark.asyncio
async def test_empty_translation_is_reported_as_invalid_result() -> None:
    workflow = TranslationWorkflow(
        executor=cast(Any, _Executor(_Capabilities())),
        cache=_Cache(),
        provider=_Provider(chunks=()),
        capacity=_Capacity(),
    )
    stream = await workflow.open_stream(
        actor=_actor(),
        operation=_operation(),
        document_id=uuid4(),
        request=TranslationRequest(text="source"),
        client_ip="127.0.0.1",
    )

    events = await _events(stream)

    assert [event.event for event in events] == ["start", "error"]
    assert events[-1].data["code"] == "translation_result_invalid"


class _BlockingIterator:
    def __init__(self) -> None:
        self.read_started = threading.Event()
        self.cancelled = threading.Event()
        self.closed = threading.Event()
        self.reader_thread_id: int | None = None
        self.close_thread_id: int | None = None

    def __iter__(self) -> _BlockingIterator:
        return self

    def __next__(self) -> str:
        self.reader_thread_id = threading.get_ident()
        self.read_started.set()
        self.cancelled.wait(timeout=5)
        raise StopIteration

    def cancel(self) -> None:
        self.cancelled.set()

    def close(self) -> None:
        self.close_thread_id = threading.get_ident()
        self.closed.set()


@pytest.mark.asyncio
async def test_blocking_iterator_cancellation_is_owned_by_reader_thread() -> None:
    iterator = _BlockingIterator()

    async def consume() -> None:
        async for _ in iterate_in_thread(iterator):
            pass

    consumer = asyncio.create_task(consume())
    assert await asyncio.to_thread(iterator.read_started.wait, 1)
    consumer.cancel()
    with suppress(asyncio.CancelledError):
        await consumer

    assert await asyncio.to_thread(iterator.closed.wait, 1)
    assert iterator.cancelled.is_set()
    assert iterator.close_thread_id == iterator.reader_thread_id


class _RedisStub:
    def __init__(
        self,
        *,
        value: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.value = value
        self.error = error
        self.deleted: list[str] = []

    async def get(self, key: str) -> str | None:
        if self.error is not None:
            raise self.error
        return self.value

    async def delete(self, key: str) -> None:
        self.deleted.append(key)


@pytest.mark.asyncio
async def test_translation_cache_is_bounded_and_fails_open() -> None:
    with patch(
        "app.modules.translations.infrastructure.cache.Redis.from_url"
    ) as from_url:
        cache = RedisTranslationCache("redis://cache")

    from_url.assert_called_once_with(
        "redis://cache",
        decode_responses=True,
        socket_connect_timeout=1.0,
        socket_timeout=1.0,
        retry_on_timeout=False,
    )

    corrupt = _RedisStub(value='{"translated_text": 12}')
    cache._client = cast(Any, corrupt)
    assert await cache.get("cache-key") is None
    assert corrupt.deleted == ["cache-key"]

    unavailable = _RedisStub(error=RedisConnectionError("offline"))
    cache._client = cast(Any, unavailable)
    assert await cache.get("cache-key") is None


@pytest.mark.asyncio
async def test_translation_sse_uses_standard_event_framing() -> None:
    async def source() -> AsyncIterator[TranslationStreamEvent]:
        yield TranslationStreamEvent(event="delta", data={"text": "译文"})

    assert [chunk async for chunk in _sse(source())] == [
        'event: delta\ndata: {"text":"译文"}\n\n'
    ]


def test_translation_openapi_declares_event_stream_response() -> None:
    response = app.openapi()["paths"][
        "/api/v1/papers/{document_id}/translations"
    ]["post"]["responses"]["200"]

    assert set(response["content"]) == {"text/event-stream"}
    assert response["content"]["text/event-stream"]["schema"] == {
        "type": "string"
    }
