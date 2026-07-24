"""Small, provider-neutral bridge for remote Streamable HTTP MCP servers."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import uuid4

import httpx
import jwt
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent as MCPTextContent
from app.llm.token_credits import current_usage_context

T = TypeVar("T")


class MCPToolError(RuntimeError):
    """A remote MCP server returned an error result."""


def normalize_json_schema(value: Any) -> Any:
    """Keep MCP schemas compatible with all configured model providers."""
    if isinstance(value, list):
        return [normalize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: normalize_json_schema(item)
        for key, item in value.items()
        if key not in {"$schema", "additionalProperties"}
    }


def function_declaration_from_mcp_tool(tool: Any, server_name: str) -> dict[str, Any]:
    """Translate an MCP tool into a provider-compatible function contract."""
    return {
        "name": tool.name,
        "description": tool.description or f"{server_name} MCP tool",
        "parameters": normalize_json_schema(tool.inputSchema),
    }


def _run_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run one async MCP operation from the existing synchronous agent loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    # Some metadata recovery paths are synchronous even when called beneath an
    # ASGI event loop. Run the short-lived MCP session in its own thread/loop.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-sync") as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


@dataclass(frozen=True, slots=True)
class RemoteMCPServer:
    """Configuration and calls for one stateless Streamable HTTP MCP server."""

    name: str
    url: str
    api_key: str | None = None
    headers_factory: Callable[[], dict[str, str]] | None = None
    allowed_tools: frozenset[str] | None = None

    @property
    def headers(self) -> dict[str, str] | None:
        if self.headers_factory is not None:
            return self.headers_factory()
        if not self.api_key:
            return None
        return {"Authorization": f"Bearer {self.api_key}"}

    async def _session_call(
        self, operation: Callable[[ClientSession], Awaitable[T]]
    ) -> T:
        async with httpx.AsyncClient(
            headers=self.headers or {},
            follow_redirects=True,
            timeout=httpx.Timeout(60),
        ) as http_client:
            async with streamable_http_client(
                self.url,
                http_client=http_client,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await operation(session)

    async def function_declarations(self) -> list[dict[str, Any]]:
        """Return MCP tools in the function schema understood by LLM providers."""

        async def _list(session: ClientSession) -> list[dict[str, Any]]:
            response = await session.list_tools()
            declarations: list[dict[str, Any]] = []
            for tool in response.tools:
                if (
                    self.allowed_tools is not None
                    and tool.name not in self.allowed_tools
                ):
                    continue
                declarations.append(function_declaration_from_mcp_tool(tool, self.name))
            return declarations

        return await self._session_call(_list)

    def function_declarations_sync(self) -> list[dict[str, Any]]:
        return _run_sync(self.function_declarations)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.allowed_tools is not None and name not in self.allowed_tools:
            raise MCPToolError(f"{self.name} does not expose allowed tool {name!r}")

        async def _call(session: ClientSession) -> Any:
            result = await session.call_tool(name, arguments)
            text_parts = [
                item.text for item in result.content if isinstance(item, MCPTextContent)
            ]
            text = "\n".join(text_parts).strip()
            if result.isError:
                raise MCPToolError(text or f"{self.name}.{name} failed")
            if result.structuredContent is not None:
                return result.structuredContent
            return text

        return await self._session_call(_call)

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> Any:
        return _run_sync(lambda: self.call_tool(name, arguments))


ANYSEARCH_MCP = RemoteMCPServer(
    name="AnySearch",
    url=os.getenv("ANYSEARCH_MCP_URL", "https://api.anysearch.com/mcp"),
    api_key=os.getenv("ANYSEARCH_API_KEY") or None,
    allowed_tools=frozenset({"search", "batch_search", "extract", "get_sub_domains"}),
)


def _scholight_delegation_headers() -> dict[str, str]:
    context = current_usage_context()
    if context is None:
        raise MCPToolError("Scholight MCP requires an authenticated user context")
    secret = os.getenv("SCHOLIGHT_MCP_DELEGATION_JWT_SECRET")
    if not secret or len(secret.encode()) < 32:
        raise MCPToolError("Scholight MCP delegation is not configured")
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "scholens",
            "aud": "scholight-mcp",
            "sub": str(context.user_id),
            "scope": "search",
            "iat": now,
            "exp": now + 60,
            "jti": str(uuid4()),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


SCHOLIGHT_MCP = RemoteMCPServer(
    name="Scholight",
    url=os.getenv(
        "SCHOLIGHT_MCP_URL",
        "https://scholight.sanchezcloud.net/api/mcp",
    ),
    headers_factory=lambda: _scholight_delegation_headers(),
    allowed_tools=frozenset({"search_papers"}),
)

REMOTE_MCP_SERVERS = (ANYSEARCH_MCP, SCHOLIGHT_MCP)


async def discover_function_declarations(
    servers: Iterable[RemoteMCPServer] = REMOTE_MCP_SERVERS,
) -> list[dict[str, Any]]:
    """Discover tools across servers and reject ambiguous duplicate names."""
    declarations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for server in servers:
        for declaration in await server.function_declarations():
            name = str(declaration["name"])
            if name in seen:
                raise RuntimeError(f"Duplicate MCP tool name {name!r}")
            seen.add(name)
            declarations.append(declaration)
    return declarations


def discover_function_declarations_sync(
    servers: Iterable[RemoteMCPServer] = REMOTE_MCP_SERVERS,
) -> list[dict[str, Any]]:
    return _run_sync(lambda: discover_function_declarations(servers))


def server_for_tool(
    tool_name: str,
    servers: Iterable[RemoteMCPServer] = REMOTE_MCP_SERVERS,
) -> RemoteMCPServer:
    matches = [
        server
        for server in servers
        if server.allowed_tools is None or tool_name in server.allowed_tools
    ]
    if len(matches) != 1:
        raise MCPToolError(f"No unique MCP server registered for tool {tool_name!r}")
    return matches[0]


async def call_remote_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    return await server_for_tool(tool_name).call_tool(tool_name, arguments)


def call_remote_tool_sync(tool_name: str, arguments: dict[str, Any]) -> Any:
    return server_for_tool(tool_name).call_tool_sync(tool_name, arguments)
