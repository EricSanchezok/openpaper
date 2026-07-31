"""Transport-neutral translation request and preference contracts."""

from __future__ import annotations

from app.modules.translations.domain import (
    MAX_CUSTOM_INSTRUCTIONS_CHARS,
    MAX_LANGUAGE_TAG_CHARS,
    MAX_SOURCE_TEXT_CHARS,
)
from app.shared.domain import AppError, FailureKind
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TranslationPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_language: str = Field(
        json_schema_extra={"maxLength": MAX_LANGUAGE_TAG_CHARS}
    )
    custom_instructions: str | None = Field(
        default=None,
        json_schema_extra={"maxLength": MAX_CUSTOM_INSTRUCTIONS_CHARS},
    )
    auto_translate_selection: bool

    @field_validator("target_language")
    @classmethod
    def guard_target_language_size(cls, value: str) -> str:
        if len(value) > MAX_LANGUAGE_TAG_CHARS:
            raise AppError(
                code="translation_language_invalid",
                message="Target language is invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return value

    @field_validator("custom_instructions")
    @classmethod
    def guard_custom_instructions_size(cls, value: str | None) -> str | None:
        if (
            value is not None
            and len(value) > MAX_CUSTOM_INSTRUCTIONS_CHARS
        ):
            raise AppError(
                code="translation_instructions_invalid",
                message="Custom translation instructions are invalid",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return value


class TranslationPreferencesResponse(BaseModel):
    target_language: str
    custom_instructions: str | None
    auto_translate_selection: bool


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        json_schema_extra={"maxLength": MAX_SOURCE_TEXT_CHARS}
    )

    @field_validator("text")
    @classmethod
    def guard_source_text_size(cls, value: str) -> str:
        if len(value) > MAX_SOURCE_TEXT_CHARS:
            raise AppError(
                code="translation_text_invalid",
                message=(
                    "Translation text must contain between 1 and "
                    f"{MAX_SOURCE_TEXT_CHARS:,} characters"
                ),
                kind=FailureKind.INVALID_ARGUMENT,
            )
        return value
