from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from app.helpers.scholight_search import search_scholight
from app.integrations.mcp import (
    MCPToolError,
    RemoteMCPServer,
    function_declaration_from_mcp_tool,
    normalize_json_schema,
    server_for_tool,
)
from app.llm.token_credits import llm_usage_context
from mcp.types import Tool


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

    assert anonymous.headers is None
    assert authenticated.headers == {"Authorization": "Bearer secret"}


def test_scholight_delegation_identifies_current_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.mcp import SCHOLIGHT_MCP

    monkeypatch.setenv("SCHOLIGHT_MCP_DELEGATION_JWT_SECRET", "d" * 32)
    with llm_usage_context(user_id=42, feature="test"):
        authorization = SCHOLIGHT_MCP.headers

    assert authorization is not None
    token = authorization["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(
        token,
        "d" * 32,
        algorithms=["HS256"],
        audience="scholight-mcp",
        issuer="openpaper",
    )
    assert (claims["sub"], claims["scope"]) == ("42", "search")


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


@pytest.mark.asyncio
async def test_scholight_mcp_response_maps_to_discover_result() -> None:
    response = {
        "query": "retrieval",
        "hits": [
            {
                "title": "A Retrieval Paper",
                "authors": ["Ada Researcher"],
                "abstract": "A ranked abstract.",
                "submitted_at": "2026-07-01T00:00:00Z",
                "arxiv_url": "https://arxiv.org/abs/2607.00001",
            }
        ],
    }

    call = AsyncMock(return_value=response)
    with patch(
        "app.helpers.scholight_search.SCHOLIGHT_MCP",
        new=SimpleNamespace(call_tool=call),
    ):
        results = await search_scholight(
            "retrieval",
            num_results=5,
            date_from="2025-07-01",
        )

    call.assert_awaited_once_with(
        "search_papers",
        {
            "query": "retrieval",
            "strength": "standard",
            "limit": 5,
            "date_from": "2025-07-01",
        },
    )
    assert [result.to_dict() for result in results] == [
        {
            "title": "A Retrieval Paper",
            "url": "https://arxiv.org/abs/2607.00001",
            "authors": ["Ada Researcher"],
            "published_date": "2026-07-01T00:00:00Z",
            "text": "A ranked abstract.",
            "highlights": [],
            "highlight_scores": [],
            "favicon": None,
            "summary": "A ranked abstract.",
            "source": "Scholight",
        }
    ]
