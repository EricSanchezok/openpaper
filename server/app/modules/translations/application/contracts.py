"""Transport-neutral translation request and preference contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranslationPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_language: str = Field(min_length=2, max_length=35)
    custom_instructions: str | None = Field(default=None, max_length=2_000)
    auto_translate_selection: bool


class TranslationPreferencesResponse(BaseModel):
    target_language: str
    custom_instructions: str | None
    auto_translate_selection: bool


class TranslationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=20_000)
