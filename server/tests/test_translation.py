from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Callable
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.bootstrap.workflows.translation import TranslationWorkflow
from app.llm.token_credits import current_usage_context
from app.modules.translations.application import (
    PreparedTranslation,
    TranslationCacheValue,
    TranslationCapacityLease,
    TranslationPreferencesRecord,
    TranslationPreferencesUpdateRequest,
    TranslationRequest,
    TranslationStreamEvent,
    TranslationStreamSpec,
    Translations,
)
from app.modules.translations.domain import (
    TranslationCacheIdentity,
    normalize_language_tag,
    normalize_source_text,
    translation_cache_key,
    translation_instructions_hash,
)
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
from app.shared.domain import AppError
from app.transport.http.public_v1.translations import _sse


def _actor(*, locale: str | None = "en-US") -> Actor:
    return Actor(
        id=42,
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
        source_text="source",
        target_language="zh-CN",
        custom_instructions_hash=translation_instructions_hash(None),
    )
    assert translation_cache_key(identity) == translation_cache_key(identity)
    assert "source" not in translation_cache_key(identity)


class _Cache:
    def __init__(self, value: TranslationCacheValue | None = None) -> None:
        self.value = value
        self.set_values: list[TranslationCacheValue] = []
        self.released: list[tuple[str, str]] = []

    async def get(self, key: str) -> TranslationCacheValue | None:
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
async def test_translation_sse_uses_standard_event_framing() -> None:
    async def source() -> AsyncIterator[TranslationStreamEvent]:
        yield TranslationStreamEvent(event="delta", data={"text": "译文"})

    assert [chunk async for chunk in _sse(source())] == [
        'event: delta\ndata: {"text":"译文"}\n\n'
    ]
