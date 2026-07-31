"""One dynamic Streamable HTTP MCP runtime for all research Connectors."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, TypeVar
from uuid import uuid4

import httpx
import jwt
from app.modules.integrations.connectors.application.ports import (
    ConnectorCredential,
    ConnectorCredentialState,
    UnreadableConnectorCredential,
)
from app.modules.integrations.connectors.domain import ConnectorProvider
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, JsonValue, WorkspacePermission
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent as MCPTextContent
from pydantic import TypeAdapter

T = TypeVar("T")
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)
_SCHEMA_CACHE_SECONDS = 300.0
_MAX_RESULT_CHARS = 150_000
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class ConnectorDefinition:
    provider: ConnectorProvider
    display_name: str
    url: str
    auth_header: str
    auth_prefix: str = ""


class ConnectorRuntimeSettings(Protocol):
    scholight_mcp_url: str
    scholight_mcp_delegation_jwt_secret: str | None


class EnabledCredentialLoader(Protocol):
    def __call__(self, actor: Actor) -> tuple[ConnectorCredentialState, ...]: ...


@dataclass(frozen=True, slots=True)
class RemoteMCPConnection:
    provider: ConnectorProvider
    display_name: str
    url: str
    headers: Mapping[str, str] = field(repr=False)
    revision: str


@dataclass(frozen=True, slots=True)
class ConnectorToolIssue:
    provider: ConnectorProvider
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class _BoundTool:
    connection: RemoteMCPConnection
    name: str


@dataclass(frozen=True, slots=True)
class ResolvedConnectorToolSet:
    declarations: tuple[dict[str, Any], ...] = ()
    issues: tuple[ConnectorToolIssue, ...] = ()
    _routes: Mapping[str, _BoundTool] = field(
        default_factory=lambda: MappingProxyType({}),
        repr=False,
    )

    def has_tool(self, name: str) -> bool:
        return name in self._routes

    def provider_for(self, name: str) -> ConnectorProvider | None:
        bound = self._routes.get(name)
        return bound.connection.provider if bound is not None else None

    async def call(self, name: str, arguments: dict[str, Any]) -> JsonValue:
        bound = self._routes.get(name)
        if bound is None:
            raise AppError(
                code="connector_tool_not_found",
                message="Connector tool is not available",
                kind=FailureKind.NOT_FOUND,
            )
        try:
            result = await _call_remote_tool(
                connection=bound.connection,
                name=bound.name,
                arguments=arguments,
            )
        except Exception as exc:
            credentials_invalid = _looks_like_authentication_error(exc)
            raise AppError(
                code=(
                    "connector_credentials_invalid"
                    if credentials_invalid
                    else "connector_tool_failed"
                ),
                message=(
                    "Connector credentials are no longer valid"
                    if credentials_invalid
                    else "External connector tool failed"
                ),
                kind=(
                    FailureKind.UNPROCESSABLE
                    if credentials_invalid
                    else FailureKind.DEPENDENCY_FAILURE
                ),
                details={
                    "provider": bound.connection.provider.value,
                    "tool": name,
                    "retryable": not credentials_invalid,
                },
            ) from exc
        return _normalize_result(result)

    def call_sync(self, name: str, arguments: dict[str, Any]) -> JsonValue:
        return _run_sync(lambda: self.call(name, arguments))


_PROVIDER_DEFINITIONS = {
    ConnectorProvider.ANYSEARCH: ConnectorDefinition(
        ConnectorProvider.ANYSEARCH,
        "AnySearch",
        "https://api.anysearch.com/mcp",
        "Authorization",
        "Bearer ",
    ),
    ConnectorProvider.TAVILY: ConnectorDefinition(
        ConnectorProvider.TAVILY,
        "Tavily",
        "https://mcp.tavily.com/mcp/",
        "Authorization",
        "Bearer ",
    ),
    ConnectorProvider.EXA: ConnectorDefinition(
        ConnectorProvider.EXA,
        "Exa",
        "https://mcp.exa.ai/mcp",
        "x-api-key",
    ),
    ConnectorProvider.FIRECRAWL: ConnectorDefinition(
        ConnectorProvider.FIRECRAWL,
        "Firecrawl",
        "https://mcp.firecrawl.dev/v2/mcp",
        "Authorization",
        "Bearer ",
    ),
}
_PROVIDER_PRIORITY = (
    ConnectorProvider.SCHOLIGHT,
    ConnectorProvider.ANYSEARCH,
    ConnectorProvider.TAVILY,
    ConnectorProvider.EXA,
    ConnectorProvider.FIRECRAWL,
)


class ConnectorToolResolver:
    def __init__(
        self,
        *,
        credential_loader: EnabledCredentialLoader,
        settings: ConnectorRuntimeSettings,
    ) -> None:
        self._credential_loader = credential_loader
        self._settings = settings
        self._schema_cache: dict[
            tuple[int, ConnectorProvider, str],
            tuple[float, tuple[dict[str, Any], ...]],
        ] = {}

    async def probe(
        self,
        *,
        provider: ConnectorProvider,
        api_key: str,
    ) -> None:
        definition = _PROVIDER_DEFINITIONS.get(provider)
        if definition is None:
            raise AppError(
                code=(
                    "connector_managed_by_system"
                    if provider is ConnectorProvider.SCHOLIGHT
                    else "connector_not_supported"
                ),
                message="Connector cannot be configured by the user",
                kind=FailureKind.CONFLICT,
            )
        connection = _external_connection(
            definition,
            api_key=api_key,
            revision="probe",
        )
        try:
            declarations = await _list_declarations(connection)
        except Exception as exc:
            if _looks_like_authentication_error(exc):
                raise AppError(
                    code="connector_credentials_invalid",
                    message="Connector API key is invalid",
                    kind=FailureKind.UNPROCESSABLE,
                ) from exc
            raise AppError(
                code="connector_unavailable",
                message="Connector is temporarily unavailable",
                kind=FailureKind.DEPENDENCY_FAILURE,
            ) from exc
        if not declarations:
            raise AppError(
                code="connector_tools_invalid",
                message="Connector did not expose any valid tools",
                kind=FailureKind.DEPENDENCY_FAILURE,
            )

    async def resolve(
        self,
        *,
        actor: Actor,
        permissions: frozenset[WorkspacePermission],
        reserved_names: set[str] | frozenset[str] = frozenset(),
    ) -> ResolvedConnectorToolSet:
        if WorkspacePermission.READ not in permissions:
            return ResolvedConnectorToolSet()
        credential_states = await asyncio.to_thread(
            self._credential_loader,
            actor,
        )
        credentials = tuple(
            state
            for state in credential_states
            if isinstance(state, ConnectorCredential)
        )
        credential_issues = tuple(
            ConnectorToolIssue(
                state.provider,
                state.code,
                f"{state.provider.value.title()} credentials could not be read; reconnect the connector",
            )
            for state in credential_states
            if isinstance(state, UnreadableConnectorCredential)
        )
        connections = self._connections(actor=actor, credentials=credentials)
        discovered = await asyncio.gather(
            *(self._discover(actor.id, connection) for connection in connections),
            return_exceptions=True,
        )
        by_provider = {
            connection.provider: (connection, result)
            for connection, result in zip(connections, discovered, strict=True)
        }
        seen = set(reserved_names)
        declarations: list[dict[str, Any]] = []
        routes: dict[str, _BoundTool] = {}
        issues: list[ConnectorToolIssue] = list(credential_issues)
        for provider in _PROVIDER_PRIORITY:
            pair = by_provider.get(provider)
            if pair is None:
                continue
            connection, result = pair
            if isinstance(result, BaseException):
                credentials_invalid = _looks_like_authentication_error(result)
                issues.append(
                    ConnectorToolIssue(
                        provider,
                        (
                            "connector_credentials_invalid"
                            if credentials_invalid
                            else "connector_unavailable"
                        ),
                        (
                            f"{connection.display_name} credentials are no longer valid"
                            if credentials_invalid
                            else f"{connection.display_name} is temporarily unavailable"
                        ),
                    )
                )
                continue
            for declaration in result:
                name = str(declaration["name"])
                if name in seen:
                    issues.append(
                        ConnectorToolIssue(
                            provider,
                            "connector_tool_name_conflict",
                            f"{connection.display_name} tool {name} was omitted because its name conflicts",
                        )
                    )
                    continue
                seen.add(name)
                declarations.append(declaration)
                routes[name] = _BoundTool(connection, name)
        return ResolvedConnectorToolSet(
            declarations=tuple(declarations),
            issues=tuple(issues),
            _routes=MappingProxyType(routes),
        )

    def resolve_sync(
        self,
        *,
        actor: Actor,
        reserved_names: set[str] | frozenset[str] = frozenset(),
    ) -> ResolvedConnectorToolSet:
        return _run_sync(
            lambda: self.resolve(
                actor=actor,
                permissions=frozenset({WorkspacePermission.READ}),
                reserved_names=reserved_names,
            )
        )

    def _connections(
        self,
        *,
        actor: Actor,
        credentials: tuple[ConnectorCredential, ...],
    ) -> tuple[RemoteMCPConnection, ...]:
        connections: list[RemoteMCPConnection] = []
        secret = self._settings.scholight_mcp_delegation_jwt_secret
        if secret and len(secret.encode()) >= 32:
            connections.append(
                RemoteMCPConnection(
                    provider=ConnectorProvider.SCHOLIGHT,
                    display_name="Scholight",
                    url=self._settings.scholight_mcp_url,
                    headers=MappingProxyType(
                        _scholight_delegation_headers(actor, secret)
                    ),
                    revision="built-in",
                )
            )
        for credential in credentials:
            definition = _PROVIDER_DEFINITIONS[credential.provider]
            connections.append(
                _external_connection(
                    definition,
                    api_key=credential.api_key,
                    revision=credential.updated_at.isoformat(),
                )
            )
        return tuple(connections)

    async def _discover(
        self,
        user_id: int,
        connection: RemoteMCPConnection,
    ) -> tuple[dict[str, Any], ...]:
        key = (user_id, connection.provider, connection.revision)
        cached = self._schema_cache.get(key)
        now = time.monotonic()
        if cached is not None and cached[0] > now:
            return cached[1]
        declarations = tuple(await _list_declarations(connection))
        self._schema_cache[key] = (now + _SCHEMA_CACHE_SECONDS, declarations)
        return declarations


async def _session_call(
    connection: RemoteMCPConnection,
    operation: Callable[[ClientSession], Awaitable[T]],
) -> T:
    async with httpx.AsyncClient(
        headers=dict(connection.headers),
        follow_redirects=False,
        timeout=httpx.Timeout(60),
    ) as http_client:
        async with streamable_http_client(
            connection.url,
            http_client=http_client,
        ) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await operation(session)


async def _list_declarations(
    connection: RemoteMCPConnection,
) -> list[dict[str, Any]]:
    async def operation(session: ClientSession) -> list[dict[str, Any]]:
        response = await session.list_tools()
        declarations: list[dict[str, Any]] = []
        for tool in response.tools:
            if not tool.name or _TOOL_NAME_PATTERN.fullmatch(tool.name) is None:
                continue
            declarations.append(
                {
                    "name": tool.name,
                    "description": (
                        tool.description
                        or f"{connection.display_name} connector tool"
                    ),
                    "parameters": _normalize_json_schema(tool.inputSchema),
                }
            )
        return declarations

    return await _session_call(connection, operation)


async def _call_remote_tool(
    *,
    connection: RemoteMCPConnection,
    name: str,
    arguments: dict[str, Any],
) -> Any:
    async def operation(session: ClientSession) -> Any:
        result = await session.call_tool(name, arguments)
        text = "\n".join(
            item.text for item in result.content if isinstance(item, MCPTextContent)
        ).strip()
        if result.isError:
            raise RuntimeError("remote connector returned an error")
        if result.structuredContent is not None:
            return result.structuredContent
        return text

    return await _session_call(connection, operation)


def _external_connection(
    definition: ConnectorDefinition,
    *,
    api_key: str,
    revision: str,
) -> RemoteMCPConnection:
    return RemoteMCPConnection(
        provider=definition.provider,
        display_name=definition.display_name,
        url=definition.url,
        headers=MappingProxyType(
            {definition.auth_header: f"{definition.auth_prefix}{api_key}"}
        ),
        revision=revision,
    )


def _scholight_delegation_headers(actor: Actor, secret: str) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "scholens",
            "aud": "scholight-mcp",
            "sub": str(actor.id),
            "scope": "search",
            "iat": now,
            "exp": now + 60,
            "jti": str(uuid4()),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _normalize_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _normalize_json_schema(item)
        for key, item in value.items()
        if key not in {"$schema", "additionalProperties"}
    }


def _normalize_result(value: Any) -> JsonValue:
    try:
        normalized = _JSON_VALUE.validate_python(value)
    except Exception:
        normalized = str(value)
    encoded = json.dumps(normalized, ensure_ascii=False, default=str)
    if len(encoded) <= _MAX_RESULT_CHARS:
        return normalized
    return {
        "truncated": True,
        "content": encoded[:_MAX_RESULT_CHARS],
    }


def _looks_like_authentication_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return any(
        marker in text
        for marker in ("401", "403", "unauthorized", "forbidden", "invalid api")
    )


def _run_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="connector-mcp") as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()
