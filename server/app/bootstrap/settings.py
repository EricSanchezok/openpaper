"""Validated process settings owned by the composition root."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PUBLIC_API_PREFIX = "/api/v1"
WEBHOOK_API_PREFIX = "/webhooks/v1"
INTERNAL_API_PREFIX = "/internal/v1"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    client_domain: str = "http://localhost:3000"
    paper_search_backend: Literal["postgres_fts"] = "postgres_fts"
