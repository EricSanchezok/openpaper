from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, cast

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.tooling import (
    ToolAccess,
    ToolCatalog,
    ToolCallContext,
    ToolDefinition,
    ToolDispatcher,
    ToolExecutionKind,
    ToolOutcome,
    ToolProfile,
)
from app.tooling.workspace import build_workspace_tool_catalog
from app.transport.mcp.server import build_mcp_transport
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from mcp.server.transport_security import TransportSecuritySettings
import pytest
from pydantic import BaseModel, ConfigDict
from starlette.applications import Starlette
from starlette.routing import Route


class RecordingDispatcher:
    def __init__(self) -> None:
        self.calls: list[
            tuple[str, dict[str, object], ToolCallContext, ToolAccess]
        ] = []
        self.error: AppError | None = None

    async def dispatch(
        self,
        *,
        name: str,
        raw_arguments: dict[str, object],
        context: ToolCallContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        self.calls.append((name, raw_arguments, context, access))
        if self.error is not None:
            raise self.error
        return ToolOutcome(payload={"tool": name, "arguments": raw_arguments})


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MinimalCapabilities:
    pass


class MinimalExecutor:
    def query(
        self,
        operation: Callable[[MinimalCapabilities], Any],
    ) -> Any:
        return operation(MinimalCapabilities())


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _application(
    catalog: ToolCatalog[Any],
    dispatcher: object,
) -> Starlette:
    async def authenticate(token: str) -> Actor:
        if token != "active-token":
            raise HTTPException(status_code=401, detail="Session revoked or expired")
        return _actor()

    manager, endpoint = build_mcp_transport(
        catalog=cast(ToolCatalog[ApplicationCapabilities], catalog),
        dispatcher=cast(
            ToolDispatcher[ApplicationCapabilities],
            dispatcher,
        ),
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["testserver"],
            allowed_origins=[],
        ),
        authenticate=authenticate,
    )

    @asynccontextmanager
    async def lifespan(_application: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    return Starlette(
        routes=[Route("/mcp", endpoint=endpoint)],
        lifespan=lifespan,
    )


def _transport() -> tuple[Starlette, RecordingDispatcher]:
    catalog = build_workspace_tool_catalog(
        ingestion=cast(PaperIngestionWorkflow, object())
    )
    recording = RecordingDispatcher()
    return _application(catalog, recording), recording


async def _initialize(client: AsyncClient) -> dict[str, str]:
    headers = {
        "authorization": "Bearer active-token",
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    response = await client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": "initialize",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        },
    )
    assert response.status_code == 200
    initialized_headers = {
        **headers,
        "mcp-protocol-version": "2025-06-18",
    }
    session_id = response.headers.get("mcp-session-id")
    if session_id is not None:
        initialized_headers["mcp-session-id"] = session_id
    return initialized_headers


@pytest.mark.asyncio
async def test_mcp_requires_an_active_bearer_session() -> None:
    application, _ = _transport()
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            missing = await client.post("/mcp", json={})
            revoked = await client.post(
                "/mcp",
                headers={"authorization": "Bearer revoked-token"},
                json={},
            )

    assert missing.status_code == 401
    assert revoked.status_code == 401


@pytest.mark.asyncio
async def test_mcp_lists_catalog_tools_and_dispatches_with_bound_actor() -> None:
    application, dispatcher = _transport()
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            listed = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "list-tools",
                    "method": "tools/list",
                    "params": {},
                },
            )
            called = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-tool",
                    "method": "tools/call",
                    "params": {
                        "name": "list_projects",
                        "arguments": {"limit": 10},
                    },
                },
            )

    tools = listed.json()["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert len(tool_names) == 32
    assert "finish_tool_use" not in tool_names
    assert called.json()["result"]["structuredContent"]["result"] == {
        "tool": "list_projects",
        "arguments": {"limit": 10},
    }
    name, arguments, context, access = dispatcher.calls[0]
    assert name == "list_projects"
    assert arguments == {"limit": 10}
    assert context.actor.id == 7
    assert context.source == "mcp"
    assert context.paper_collection.kind == "library"
    assert context.anchor_document_id is None
    assert access.permissions == frozenset(WorkspacePermission)


@pytest.mark.asyncio
async def test_mcp_maps_application_errors_to_structured_tool_errors() -> None:
    application, dispatcher = _transport()
    dispatcher.error = AppError(
        kind=FailureKind.PERMISSION_DENIED,
        code="project_access_denied",
        message="Project access denied",
        details={"project_id": "missing"},
    )
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-tool",
                    "method": "tools/call",
                    "params": {
                        "name": "list_projects",
                        "arguments": {},
                    },
                },
            )

    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == {
        "kind": "permission_denied",
        "code": "project_access_denied",
        "message": "Project access denied",
        "details": {"project_id": "missing"},
    }


@pytest.mark.asyncio
async def test_mcp_call_runs_through_the_shared_dispatcher() -> None:
    catalog = ToolCatalog(
        [
            ToolDefinition(
                name="who_am_i",
                description="Return the authenticated actor.",
                input_model=EmptyInput,
                execution=ToolExecutionKind.QUERY,
                required_permission=WorkspacePermission.READ,
                handler=lambda _capabilities, context, _arguments: ToolOutcome(
                    payload={"actor_id": context.actor.id}
                ),
            )
        ],
        [ToolProfile(name="mcp", tool_names=frozenset({"who_am_i"}))],
    )
    dispatcher = ToolDispatcher(catalog=catalog, executor=MinimalExecutor())
    application = _application(catalog, dispatcher)
    async with application.router.lifespan_context(application):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            headers = await _initialize(client)
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": "call-tool",
                    "method": "tools/call",
                    "params": {"name": "who_am_i", "arguments": {}},
                },
            )

    assert response.json()["result"]["structuredContent"]["result"] == {"actor_id": 7}
