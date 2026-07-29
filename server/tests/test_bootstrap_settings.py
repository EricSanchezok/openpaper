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
    )

    assert settings.environment == "production"
