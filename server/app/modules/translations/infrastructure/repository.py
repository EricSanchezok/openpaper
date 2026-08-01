"""SQLAlchemy translation preference adapter."""

from __future__ import annotations

from app.modules.translations.application.ports import (
    TranslationPreferencesRecord,
)
from app.modules.translations.infrastructure.models import TranslationPreference
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


class SqlAlchemyTranslationPreferences:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, *, user_id: int) -> TranslationPreferencesRecord | None:
        model = self._db.get(TranslationPreference, user_id)
        return _record(model) if model is not None else None

    def upsert(
        self,
        *,
        user_id: int,
        preferences: TranslationPreferencesRecord,
    ) -> TranslationPreferencesRecord:
        statement = (
            insert(TranslationPreference)
            .values(
                user_id=user_id,
                target_language=preferences.target_language,
                custom_instructions=preferences.custom_instructions,
                auto_translate_selection=preferences.auto_translate_selection,
            )
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    "target_language": preferences.target_language,
                    "custom_instructions": preferences.custom_instructions,
                    "auto_translate_selection": (preferences.auto_translate_selection),
                    "updated_at": func.now(),
                },
            )
            .returning(TranslationPreference)
        )
        model = self._db.execute(statement).scalar_one()
        return _record(model)


def _record(model: TranslationPreference) -> TranslationPreferencesRecord:
    return TranslationPreferencesRecord(
        target_language=model.target_language,
        custom_instructions=model.custom_instructions,
        auto_translate_selection=model.auto_translate_selection,
    )
