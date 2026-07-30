from __future__ import annotations

from pathlib import Path

import pytest

from app.transport.client_ip import (
    MAX_CLIENT_IP_LENGTH,
    UNKNOWN_CLIENT_IP,
    normalize_client_ip,
)

ROOT = Path(__file__).parents[2]
APP_ROOT = ROOT / "server" / "app"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" 127.0.0.1 ", "127.0.0.1"),
        ("2001:0db8:0:0:0:0:0:1", "2001:db8::1"),
        ("", UNKNOWN_CLIENT_IP),
        ("not-an-ip", UNKNOWN_CLIENT_IP),
        (None, UNKNOWN_CLIENT_IP),
        ("1" * (MAX_CLIENT_IP_LENGTH + 1), UNKNOWN_CLIENT_IP),
    ],
)
def test_client_ip_normalization_is_canonical_bounded_and_nonempty(
    raw: object | None,
    expected: str,
) -> None:
    normalized = normalize_client_ip(raw)

    assert normalized == expected
    assert normalized
    assert len(normalized) <= MAX_CLIENT_IP_LENGTH


def test_client_ip_is_normalized_once_at_transport_boundaries() -> None:
    paths = (
        APP_ROOT / "transport" / "http" / "public_v1" / "discovery.py",
        APP_ROOT / "transport" / "http" / "public_v1" / "document_uploads.py",
        APP_ROOT / "transport" / "http" / "public_v1" / "research_generation.py",
        APP_ROOT / "transport" / "http" / "public_v1" / "messages.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert "http_client_ip(" in source
        assert "def _client_ip" not in source
        assert ".client.host" not in source

    mcp_source = (APP_ROOT / "transport" / "mcp" / "server.py").read_text(
        encoding="utf-8"
    )
    assert "normalize_client_ip(" in mcp_source
    assert 'default="mcp"' not in mcp_source


def test_client_ip_does_not_enter_provenance_or_durable_ledgers() -> None:
    operation_context = (
        APP_ROOT / "shared" / "application" / "operation_context.py"
    ).read_text(encoding="utf-8")
    journal_model = (
        APP_ROOT / "modules" / "operation_journal" / "infrastructure" / "models.py"
    ).read_text(encoding="utf-8")
    invocation_model = (
        APP_ROOT / "database" / "models" / "tool_invocation.py"
    ).read_text(encoding="utf-8")

    assert "client_ip" not in operation_context
    assert "client_ip" not in journal_model
    assert "client_ip" not in invocation_model
