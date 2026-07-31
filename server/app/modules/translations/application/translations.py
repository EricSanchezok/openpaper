"""Translation preference use cases and preflight validation."""

from __future__ import annotations

from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.translations.application.contracts import (
    TranslationPreferencesResponse,
    TranslationPreferencesUpdateRequest,
    TranslationRequest,
)
from app.modules.translations.application.ports import (
    PreparedTranslation,
    TranslationEntitlements,
    TranslationPreferencesGateway,
    TranslationPreferencesRecord,
)
from app.modules.translations.domain import (
    normalize_custom_instructions,
    normalize_language_tag,
    normalize_source_text,
    resolve_target_language,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind

TRANSLATION_PREFERENCES_UPDATED = OperationAction(
    "translation.preferences_updated"
)


class Translations:
    def __init__(
        self,
        *,
        gateway: TranslationPreferencesGateway,
        entitlements: TranslationEntitlements,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._entitlements = entitlements
        self._journal = journal

    def preferences(self, *, actor: Actor) -> TranslationPreferencesResponse:
        record = self._gateway.get(user_id=actor.id)
        return self._response(record=record, actor_locale=actor.locale)

    def update_preferences(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: TranslationPreferencesUpdateRequest,
    ) -> TranslationPreferencesResponse:
        try:
            target_language = normalize_language_tag(request.target_language)
        except ValueError:
            raise AppError(
                code="translation_language_invalid",
                message="Target language is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from None
        try:
            custom_instructions = normalize_custom_instructions(
                request.custom_instructions
            )
        except ValueError:
            raise AppError(
                code="translation_instructions_invalid",
                message="Custom translation instructions are invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from None
        record = self._gateway.upsert(
            user_id=actor.id,
            preferences=TranslationPreferencesRecord(
                target_language=target_language,
                custom_instructions=custom_instructions,
                auto_translate_selection=request.auto_translate_selection,
            ),
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=TRANSLATION_PREFERENCES_UPDATED,
            resources=(ResourceRef("translation_preferences", str(actor.id)),),
        )
        return self._response(record=record, actor_locale=actor.locale)

    def prepare(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        paper_title: str | None,
        request: TranslationRequest,
    ) -> PreparedTranslation:
        try:
            source_text = normalize_source_text(request.text)
        except ValueError:
            raise AppError(
                code="translation_text_invalid",
                message="Translation text must contain between 1 and 5,000 characters",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from None
        preferences = self.preferences(actor=actor)
        return PreparedTranslation(
            document_id=document_id,
            paper_title=paper_title,
            source_text=source_text,
            target_language=preferences.target_language,
            custom_instructions=preferences.custom_instructions,
        )

    def require_token_credits(self, *, actor: Actor) -> None:
        if not self._entitlements.has_token_credits(actor=actor):
            raise AppError(
                code="token_quota_exceeded",
                message="Token Credits are exhausted",
                kind=FailureKind.RATE_LIMITED,
            )

    @staticmethod
    def _response(
        *,
        record: TranslationPreferencesRecord | None,
        actor_locale: str | None,
    ) -> TranslationPreferencesResponse:
        return TranslationPreferencesResponse(
            target_language=resolve_target_language(
                stored_language=(
                    record.target_language if record is not None else None
                ),
                actor_locale=actor_locale,
            ),
            custom_instructions=(
                record.custom_instructions if record is not None else None
            ),
            auto_translate_selection=(
                record.auto_translate_selection if record is not None else True
            ),
        )
