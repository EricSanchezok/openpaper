from uuid import UUID

import pytest
from app.shared.application.canonical_digest import canonical_sha256
from app.transport.mcp.references import (
    MCP_INVOCATION_DOMAIN,
    MCP_REQUEST_REFERENCE_DOMAIN,
    MCP_SESSION_REFERENCE_DOMAIN,
    mcp_invocation_id,
    mcp_request_reference,
    mcp_session_reference,
    validate_mcp_session_id,
)


def test_canonical_digest_preserves_scalar_type_and_boundaries() -> None:
    assert canonical_sha256("test.v1", "1") != canonical_sha256("test.v1", 1)
    assert canonical_sha256("test.v1", "a", "bc") != canonical_sha256(
        "test.v1",
        "ab",
        "c",
    )
    assert canonical_sha256("test.v1", UUID(int=1)) != canonical_sha256(
        "test.v1",
        str(UUID(int=1)),
    )
    assert canonical_sha256("test.v1", None) != canonical_sha256("test.v1", "")


def test_canonical_digest_rejects_empty_domain_and_boolean() -> None:
    with pytest.raises(ValueError):
        canonical_sha256("")
    with pytest.raises(TypeError):
        canonical_sha256("test.v1", True)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "has spaces",
        "contains/slash",
        "x" * 129,
        "å",
    ],
)
def test_mcp_session_id_validation_is_bounded(value: str) -> None:
    with pytest.raises(ValueError):
        validate_mcp_session_id(value)


def test_mcp_references_use_distinct_versioned_domains() -> None:
    access_key_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    session_id = "session_123"

    invocation = mcp_invocation_id(
        access_key_id=access_key_id,
        session_id=session_id,
        request_id="7",
    )
    assert invocation == (
        "mcp:"
        + canonical_sha256(
            MCP_INVOCATION_DOMAIN,
            access_key_id,
            session_id,
            "7",
        )
    )
    assert invocation != mcp_invocation_id(
        access_key_id=access_key_id,
        session_id=session_id,
        request_id=7,
    )
    assert mcp_session_reference(session_id) == canonical_sha256(
        MCP_SESSION_REFERENCE_DOMAIN,
        session_id,
    )
    assert mcp_request_reference("7") == canonical_sha256(
        MCP_REQUEST_REFERENCE_DOMAIN,
        "7",
    )
