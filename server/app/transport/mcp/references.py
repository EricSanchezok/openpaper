"""Canonical, non-sensitive MCP request identities."""

from __future__ import annotations

import re
from uuid import UUID

from app.shared.application.canonical_digest import (
    CanonicalDigestValue,
    canonical_sha256,
)

MCP_INVOCATION_DOMAIN = "scholens.mcp.invocation.v1"
MCP_SESSION_REFERENCE_DOMAIN = "scholens.mcp.session_ref.v1"
MCP_REQUEST_REFERENCE_DOMAIN = "scholens.mcp.request_ref.v1"

_MCP_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{1,128}$")


def validate_mcp_session_id(value: str) -> str:
    if _MCP_SESSION_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("MCP session ID is invalid")
    return value


def mcp_invocation_id(
    *,
    access_key_id: UUID,
    session_id: str,
    request_id: str | int,
) -> str:
    validate_mcp_session_id(session_id)
    digest = canonical_sha256(
        MCP_INVOCATION_DOMAIN,
        access_key_id,
        session_id,
        request_id,
    )
    return f"mcp:{digest}"


def mcp_session_reference(session_id: str) -> str:
    return canonical_sha256(
        MCP_SESSION_REFERENCE_DOMAIN,
        validate_mcp_session_id(session_id),
    )


def mcp_request_reference(request_id: CanonicalDigestValue) -> str:
    return canonical_sha256(MCP_REQUEST_REFERENCE_DOMAIN, request_id)
