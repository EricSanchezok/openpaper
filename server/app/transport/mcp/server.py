"""Authenticated Streamable HTTP MCP adapter over the canonical tool catalog."""

from __future__ import annotations

import json
import hashlib
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import cast

import mcp.types as mcp_types
from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, JsonValue
from app.tooling import ToolCallContext, ToolCatalog, ToolDispatcher
from app.tooling.workspace import MCP_TOOL_PROFILE
from fastapi import HTTPException
from mcp.server import Server
from mcp.server.lowlevel.server import request_ctx
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)

McpAuthenticator = Callable[[str], Awaitable[Actor]]
ListToolsHandler = Callable[[], Awaitable[list[mcp_types.Tool]]]
CallToolHandler = Callable[
    [str, dict[str, object]],
    Awaitable[mcp_types.CallToolResult],
]

_actor_context: ContextVar[Actor | None] = ContextVar("mcp_actor", default=None)
_client_ip_context: ContextVar[str] = ContextVar("mcp_client_ip", default="mcp")
_session_context: ContextVar[str] = ContextVar("mcp_session", default="anonymous")


def _error_result(
    *,
    kind: FailureKind,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> mcp_types.CallToolResult:
    safe_details = (
        cast(
            dict[str, object],
            json.loads(json.dumps(details, default=str)),
        )
        if details is not None
        else None
    )
    error = {
        "kind": kind.value,
        "code": code,
        "message": message,
        "details": safe_details,
    }
    return mcp_types.CallToolResult(
        content=[
            mcp_types.TextContent(
                type="text",
                text=json.dumps({"error": error}, separators=(",", ":")),
            )
        ],
        structuredContent={"error": error},
        isError=True,
    )


def _outcome_payload(
    *,
    payload: JsonValue,
    evidence: dict[str, list[str]],
    artifacts: list[dict[str, JsonValue]],
    action: dict[str, JsonValue] | None,
) -> dict[str, object]:
    return {
        "result": payload,
        "evidence": evidence,
        "artifacts": artifacts,
        "action": action,
    }


class AuthenticatedMcpApplication:
    """Resolve one active Scholens actor before entering the MCP protocol."""

    def __init__(
        self,
        *,
        manager: StreamableHTTPSessionManager,
        authenticate: McpAuthenticator,
    ) -> None:
        self._manager = manager
        self._authenticate = authenticate

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        authorization = headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            await self._send_auth_error(
                send,
                status_code=401,
                message="Not authenticated",
            )
            return

        try:
            actor = await self._authenticate(token)
        except HTTPException as exc:
            await self._send_auth_error(
                send,
                status_code=exc.status_code,
                message=str(exc.detail),
            )
            return
        except AppError as exc:
            status_code = {
                FailureKind.UNAUTHENTICATED: 401,
                FailureKind.PERMISSION_DENIED: 403,
                FailureKind.UNAVAILABLE: 503,
            }.get(exc.kind, 403)
            await self._send_auth_error(
                send,
                status_code=status_code,
                message=exc.message,
            )
            return
        except Exception:
            logger.exception("MCP authentication failed")
            await self._send_auth_error(
                send,
                status_code=503,
                message="Authentication service unavailable",
            )
            return

        client = scope.get("client")
        client_ip = str(client[0]) if client else "mcp"
        session_id = headers.get("mcp-session-id") or headers.get("x-request-id")
        session_id = session_id or hashlib.sha256(token.encode()).hexdigest()[:32]
        actor_token = _actor_context.set(actor)
        client_token = _client_ip_context.set(client_ip)
        session_token = _session_context.set(session_id)
        try:
            await self._manager.handle_request(scope, receive, send)
        finally:
            _session_context.reset(session_token)
            _client_ip_context.reset(client_token)
            _actor_context.reset(actor_token)

    @staticmethod
    async def _send_auth_error(
        send: Send,
        *,
        status_code: int,
        message: str,
    ) -> None:
        body = json.dumps(
            {"error": {"code": "mcp_authentication_failed", "message": message}},
            separators=(",", ":"),
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_mcp_transport(
    *,
    catalog: ToolCatalog[ApplicationCapabilities],
    dispatcher: ToolDispatcher[ApplicationCapabilities],
    security_settings: TransportSecuritySettings,
    authenticate: McpAuthenticator,
) -> tuple[StreamableHTTPSessionManager, AuthenticatedMcpApplication]:
    server: Server[object] = Server(
        "scholens",
        version="1.0.0",
        instructions="Research and manage the authenticated user's Scholens workspace.",
    )
    definitions = catalog.definitions_for(MCP_TOOL_PROFILE)
    allowed_names = frozenset(definition.name for definition in definitions)

    register_list_tools = cast(
        Callable[[], Callable[[ListToolsHandler], ListToolsHandler]],
        server.list_tools,
    )

    @register_list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=definition.name,
                description=definition.description,
                inputSchema=definition.input_model.model_json_schema(),
            )
            for definition in definitions
        ]

    register_call_tool = cast(
        Callable[..., Callable[[CallToolHandler], CallToolHandler]],
        server.call_tool,
    )

    @register_call_tool(validate_input=False)
    async def call_tool(
        name: str,
        arguments: dict[str, object],
    ) -> mcp_types.CallToolResult:
        if name not in allowed_names:
            return _error_result(
                kind=FailureKind.NOT_FOUND,
                code="tool_not_found",
                message="Tool not found",
                details={"tool_name": name},
            )
        actor = _actor_context.get()
        if actor is None:
            return _error_result(
                kind=FailureKind.UNAUTHENTICATED,
                code="mcp_authentication_required",
                message="Authentication is required",
            )
        current_request = request_ctx.get()
        invocation_id = f"mcp:{_session_context.get()}:{current_request.request_id}"
        try:
            outcome = await dispatcher.dispatch(
                name=name,
                raw_arguments=arguments,
                context=ToolCallContext(
                    actor=actor,
                    paper_collection=LibraryPaperCollection(),
                    anchor_document_id=None,
                    source="mcp",
                    invocation_id=invocation_id,
                    client_ip=_client_ip_context.get(),
                ),
            )
        except AppError as exc:
            return _error_result(
                kind=exc.kind,
                code=exc.code,
                message=exc.message,
                details=exc.details,
            )
        except Exception:
            logger.exception("MCP tool execution failed", extra={"tool_name": name})
            return _error_result(
                kind=FailureKind.UNAVAILABLE,
                code="tool_execution_failed",
                message="Tool execution failed",
            )

        structured = _outcome_payload(
            payload=outcome.payload,
            evidence=outcome.evidence,
            artifacts=outcome.artifacts,
            action=outcome.action,
        )
        return mcp_types.CallToolResult(
            content=[
                mcp_types.TextContent(
                    type="text",
                    text=json.dumps(structured, separators=(",", ":")),
                )
            ],
            structuredContent=structured,
            isError=False,
        )

    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=security_settings,
    )
    application = AuthenticatedMcpApplication(
        manager=manager,
        authenticate=authenticate,
    )
    return manager, application


__all__ = [
    "AuthenticatedMcpApplication",
    "McpAuthenticator",
    "build_mcp_transport",
]
