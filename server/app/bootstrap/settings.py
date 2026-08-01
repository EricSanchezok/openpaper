"""Validated process settings owned by the composition root."""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PUBLIC_API_PREFIX = "/api/v1"
WEBHOOK_API_PREFIX = "/webhooks/v1"
INTERNAL_API_PREFIX = "/internal/v1"
_DEVELOPMENT_CONNECTOR_KEY = "ZGV2ZWxvcG1lbnQtY29ubmVjdG9yLWtleS0zMiEhISE="


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    release_sha: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    diagnostic_snapshot_bucket: str | None = None
    diagnostic_snapshot_kms_key_id: str | None = None
    diagnostic_success_sample_rate: float = Field(default=0.01, ge=0, le=1)
    client_domain: str = "http://localhost:3000"
    paper_search_backend: Literal["postgres_fts"] = "postgres_fts"
    paper_search_cursor_secret: str = Field(
        default="development-only-search-cursor-secret",
        min_length=32,
    )
    ai_limit_redis_url: str | None = None
    translation_cache_redis_url: str | None = None
    connector_credential_encryption_key: str = _DEVELOPMENT_CONNECTOR_KEY
    scholight_mcp_url: str = "https://scholight.sanchezcloud.net/api/mcp"
    scholight_mcp_delegation_jwt_secret: str | None = None

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> AppSettings:
        try:
            connector_key = base64.urlsafe_b64decode(
                self.connector_credential_encryption_key.encode()
            )
        except Exception as exc:
            raise ValueError(
                "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY must be URL-safe base64"
            ) from exc
        if len(connector_key) != 32:
            raise ValueError(
                "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY must decode to 32 bytes"
            )
        if (
            self.environment.casefold() == "production"
            and self.paper_search_cursor_secret
            == "development-only-search-cursor-secret"
        ):
            raise ValueError("PAPER_SEARCH_CURSOR_SECRET is required in production")
        if (
            self.environment.casefold() == "production"
            and self.connector_credential_encryption_key == _DEVELOPMENT_CONNECTOR_KEY
        ):
            raise ValueError(
                "CONNECTOR_CREDENTIAL_ENCRYPTION_KEY is required in production"
            )
        if self.environment.casefold() == "production" and (
            self.scholight_mcp_delegation_jwt_secret is None
            or len(self.scholight_mcp_delegation_jwt_secret.encode()) < 32
        ):
            raise ValueError(
                "SCHOLIGHT_MCP_DELEGATION_JWT_SECRET is required in production"
            )
        return self
