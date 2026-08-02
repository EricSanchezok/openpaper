import pytest
from app.bootstrap.settings import AppSettings
from pydantic import ValidationError


def test_production_requires_a_dedicated_search_cursor_secret() -> None:
    with pytest.raises(ValidationError):
        AppSettings(
            environment="production",
            paper_search_cursor_secret="development-only-search-cursor-secret",
        )


def test_production_accepts_a_dedicated_search_cursor_secret() -> None:
    settings = AppSettings(
        environment="production",
        paper_search_cursor_secret="production-search-cursor-secret-value",
        connector_credential_encryption_key=(
            "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M="
        ),
        scholight_mcp_delegation_jwt_secret="s" * 32,
    )

    assert settings.environment == "production"


def test_cors_allowed_origins_supports_parallel_frontends() -> None:
    settings = AppSettings(
        client_domain="http://localhost:3000",
        client_allowed_origins=(
            "http://localhost:3000, http://localhost:3001,http://localhost:3000"
        ),
    )

    assert settings.cors_allowed_origins == [
        "http://localhost:3000",
        "http://localhost:3001",
    ]


def test_cors_allowed_origins_defaults_to_canonical_client_domain() -> None:
    settings = AppSettings(
        client_domain="http://localhost:3000",
        client_allowed_origins=None,
    )

    assert settings.cors_allowed_origins == ["http://localhost:3000"]
