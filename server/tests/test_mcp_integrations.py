from __future__ import annotations

import jwt
import pytest
from app.shared.application import Actor
from app.modules.conversations.infrastructure.mcp_client import (
    MCPToolError,
    RemoteMCPServer,
    function_declaration_from_mcp_tool,
    normalize_json_schema,
    server_for_tool,
)
from mcp.types import Tool


def actor(user_id: int = 42) -> Actor:
    return Actor(
        id=user_id,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def test_mcp_tool_schema_is_forwarded_to_llm_backend() -> None:
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    declaration = function_declaration_from_mcp_tool(
        Tool(name="search", description="Search the web", inputSchema=schema),
        "AnySearch",
    )

    assert declaration == {
        "name": "search",
        "description": "Search the web",
        "parameters": schema,
    }


def test_mcp_schema_drops_provider_incompatible_metadata() -> None:
    assert normalize_json_schema(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "params": {
                    "type": "object",
                    "additionalProperties": True,
                }
            },
        }
    ) == {
        "type": "object",
        "properties": {"params": {"type": "object"}},
    }


def test_remote_mcp_auth_header_is_optional() -> None:
    anonymous = RemoteMCPServer("Anonymous", "https://example.com/mcp")
    authenticated = RemoteMCPServer(
        "Authenticated",
        "https://example.com/mcp",
        api_key="secret",
    )

    assert anonymous.authorization_headers(actor=None) == {}
    assert authenticated.authorization_headers(actor=None) == {
        "Authorization": "Bearer secret"
    }


def test_scholight_delegation_identifies_current_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.conversations.infrastructure.mcp_client import SCHOLIGHT_MCP

    monkeypatch.setenv("SCHOLIGHT_MCP_DELEGATION_JWT_SECRET", "d" * 32)
    authorization = SCHOLIGHT_MCP.authorization_headers(actor=actor())

    assert authorization is not None
    token = authorization["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        token,
        "d" * 32,
        algorithms=["HS256"],
        audience="scholight-mcp",
        issuer="scholens",
    )
    assert (claims["sub"], claims["scope"]) == ("42", "search")


def test_scholight_delegation_requires_explicit_actor() -> None:
    from app.modules.conversations.infrastructure.mcp_client import SCHOLIGHT_MCP

    with pytest.raises(MCPToolError, match="authenticated actor"):
        SCHOLIGHT_MCP.authorization_headers(actor=None)


def test_tool_router_requires_one_unique_server() -> None:
    anysearch = RemoteMCPServer(
        "AnySearch",
        "https://example.com/anysearch",
        allowed_tools=frozenset({"search", "extract"}),
    )
    scholight = RemoteMCPServer(
        "Scholight",
        "https://example.com/scholight",
        allowed_tools=frozenset({"search_papers"}),
    )

    assert server_for_tool("extract", (anysearch, scholight)) is anysearch
    assert server_for_tool("search_papers", (anysearch, scholight)) is scholight
    with pytest.raises(MCPToolError):
        server_for_tool("unknown", (anysearch, scholight))
