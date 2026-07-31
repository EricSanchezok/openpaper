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
from urllib.parse import quote
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
_SCHEMA_CACHE_MAX_ENTRIES = 2_048
_MAX_RESULT_CHARS = 150_000
_MAX_TOOLS_PER_CONNECTOR = 128
_MAX_TOOL_DESCRIPTION_CHARS = 8_000
_MAX_TOOL_SCHEMA_CHARS = 100_000
_MAX_CONNECTOR_SCHEMA_CHARS = 500_000
_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class ConnectorDefinition:
    provider: ConnectorProvider
    display_name: str
    url_template: str
    auth_header: str | None
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
    url: str = field(repr=False)
    headers: Mapping[str, str] = field(repr=False)
    revision: str
    header_factory: Callable[[], Mapping[str, str]] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def request_headers(self) -> Mapping[str, str]:
        if self.header_factory is not None:
            return self.header_factory()
        return self.headers


@dataclass(frozen=True, slots=True)
class ConnectorToolIssue:
    provider: ConnectorProvider
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class _BoundTool:
    connection: RemoteMCPConnection
    name: str


class _ConnectorToolsInvalid(ValueError):
    pass


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
        "https://mcp.firecrawl.dev/{api_key}/v2/mcp",
        None,
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
            await _list_declarations(connection)
        except Exception as exc:
            if _exception_contains(exc, _ConnectorToolsInvalid):
                raise AppError(
                    code="connector_tools_invalid",
                    message="Connector exposed invalid tools",
                    kind=FailureKind.DEPENDENCY_FAILURE,
                ) from exc
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

    async def resolve(
        self,
        *,
        actor: Actor,
        permissions: frozenset[WorkspacePermission],
        reserved_names: set[str] | frozenset[str] = frozenset(),
    ) -> ResolvedConnectorToolSet:
        if WorkspacePermission.READ not in permissions:
            return ResolvedConnectorToolSet()
        self._prune_schema_cache()
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
                tools_invalid = _exception_contains(result, _ConnectorToolsInvalid)
                credentials_invalid = _looks_like_authentication_error(result)
                if tools_invalid:
                    issue_code = "connector_tools_invalid"
                    issue_message = (
                        f"{connection.display_name} exposed invalid tools"
                    )
                elif (
                    credentials_invalid
                    and provider is not ConnectorProvider.SCHOLIGHT
                ):
                    issue_code = "connector_credentials_invalid"
                    issue_message = (
                        f"{connection.display_name} credentials are no longer valid"
                    )
                else:
                    issue_code = "connector_unavailable"
                    issue_message = (
                        f"{connection.display_name} is temporarily unavailable"
                    )
                issues.append(
                    ConnectorToolIssue(
                        provider,
                        issue_code,
                        issue_message,
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
                    headers=MappingProxyType({}),
                    revision="built-in",
                    header_factory=lambda: _scholight_delegation_headers(
                        actor,
                        secret,
                    ),
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

    def _prune_schema_cache(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, (expires_at, _) in self._schema_cache.items()
            if expires_at <= now
        ]
        for key in expired:
            self._schema_cache.pop(key, None)
        overflow = len(self._schema_cache) - _SCHEMA_CACHE_MAX_ENTRIES
        if overflow <= 0:
            return
        oldest = sorted(
            self._schema_cache,
            key=lambda key: self._schema_cache[key][0],
        )
        for key in oldest[:overflow]:
            self._schema_cache.pop(key, None)


async def _session_call(
    connection: RemoteMCPConnection,
    operation: Callable[[ClientSession], Awaitable[T]],
) -> T:
    async with httpx.AsyncClient(
        headers=dict(connection.request_headers()),
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
        if len(response.tools) > _MAX_TOOLS_PER_CONNECTOR:
            raise _ConnectorToolsInvalid("connector exposed too many tools")
        declarations: list[dict[str, Any]] = []
        total_schema_chars = 0
        for tool in response.tools:
            if not tool.name or _TOOL_NAME_PATTERN.fullmatch(tool.name) is None:
                continue
            description = (
                tool.description or f"{connection.display_name} connector tool"
            )
            description = _bounded_tool_description(description)
            parameters = _normalize_json_schema(tool.inputSchema)
            if not isinstance(parameters, dict) or parameters.get("type") not in {
                None,
                "object",
            }:
                raise _ConnectorToolsInvalid("connector tool schema is not an object")
            schema_chars = len(
                json.dumps(parameters, ensure_ascii=False, separators=(",", ":"))
            )
            if schema_chars > _MAX_TOOL_SCHEMA_CHARS:
                raise _ConnectorToolsInvalid("connector tool schema is too large")
            total_schema_chars += schema_chars + len(description)
            if total_schema_chars > _MAX_CONNECTOR_SCHEMA_CHARS:
                raise _ConnectorToolsInvalid("connector tool catalog is too large")
            declarations.append(
                {
                    "name": tool.name,
                    "description": description,
                    "parameters": parameters,
                }
            )
        if not declarations:
            raise _ConnectorToolsInvalid("connector exposed no valid tools")
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
    encoded_api_key = quote(api_key, safe="")
    url = definition.url_template.format(api_key=encoded_api_key)
    headers = (
        {}
        if definition.auth_header is None
        else {
            definition.auth_header: f"{definition.auth_prefix}{api_key}"
        }
    )
    return RemoteMCPConnection(
        provider=definition.provider,
        display_name=definition.display_name,
        url=url,
        headers=MappingProxyType(headers),
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


def _bounded_tool_description(description: str) -> str:
    return description[:_MAX_TOOL_DESCRIPTION_CHARS]


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
    messages: list[str] = []
    for current in _walk_exceptions(exc):
        if (
            isinstance(current, httpx.HTTPStatusError)
            and current.response.status_code in {401, 403}
        ):
            return True
        messages.append(str(current))
    text = " ".join(messages).casefold()
    return any(
        marker in text
        for marker in ("401", "403", "unauthorized", "forbidden", "invalid api")
    )


def _exception_contains(
    exc: BaseException,
    exception_type: type[BaseException],
) -> bool:
    return any(isinstance(item, exception_type) for item in _walk_exceptions(exc))


def _walk_exceptions(exc: BaseException) -> tuple[BaseException, ...]:
    pending = [exc]
    seen: set[int] = set()
    result: list[BaseException] = []
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        result.append(current)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return tuple(result)


def _run_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="connector-mcp") as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()
