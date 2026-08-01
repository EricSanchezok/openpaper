"""Canonical HTTP request identity, logging and metric boundary."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic
from typing import Any
from uuid import uuid4

from app.shared.application import OperationContext
from scholens_observability import (
    ObservabilityContext,
    add_counter,
    bind_context,
    log_event,
    record_histogram,
    update_context,
)
from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


def attach_operation_context(
    request: Request,
    operation: OperationContext,
    *,
    actor_id: str | None = None,
) -> None:
    """Project authenticated business provenance into diagnostic context."""

    request.state.operation_context = operation
    request.state.operation_id = str(operation.trace.operation_id)
    request.state.correlation_id = str(operation.trace.correlation_id)
    if actor_id is not None:
        request.state.actor_id = actor_id
    update_context(
        actor_id=actor_id,
        operation_id=str(operation.trace.operation_id),
        correlation_id=str(operation.trace.correlation_id),
        causation_id=(
            str(operation.trace.causation_id)
            if operation.trace.causation_id is not None
            else None
        ),
        origin=operation.origin.kind,
    )


class RequestObservabilityMiddleware:
    """Keep diagnostic context alive until a streamed response fully closes."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        service: str,
        environment: str,
        release: str | None,
    ) -> None:
        self._app = app
        self._base_context = ObservabilityContext(
            service=service,
            environment=environment,
            release=release,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_id = str(uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        started = monotonic()
        response_status = 500
        response_started = False

        async def observed_send(message: Message) -> None:
            nonlocal response_status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                response_status = int(message["status"])
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                correlation_id = state.get("correlation_id")
                if isinstance(correlation_id, str):
                    headers.append(
                        (b"x-correlation-id", correlation_id.encode("ascii"))
                    )
                message["headers"] = headers
            await send(message)

        with bind_context(**self._base_context.fields(), request_id=request_id):
            log_event(
                logger,
                logging.INFO,
                "http.request.started",
                method=scope.get("method", "UNKNOWN"),
                path=scope.get("path", ""),
            )
            try:
                await self._app(scope, receive, observed_send)
            except asyncio.CancelledError:
                duration_ms = (monotonic() - started) * 1000
                add_counter("scholens.http.client_disconnected")
                log_event(
                    logger,
                    logging.INFO,
                    "http.request.client_disconnected",
                    method=scope.get("method", "UNKNOWN"),
                    route=_route_template(scope),
                    duration_ms=round(duration_ms, 3),
                )
                raise
            finally:
                duration_ms = (monotonic() - started) * 1000
                route = _route_template(scope)
                attributes: dict[str, str | int | float | bool] = {
                    "method": str(scope.get("method", "UNKNOWN")),
                    "route": route,
                    "status_code": response_status,
                }
                add_counter("scholens.http.requests", attributes=attributes)
                record_histogram(
                    "scholens.http.duration",
                    duration_ms,
                    attributes=attributes,
                )
                if response_status >= 500:
                    add_counter("scholens.http.server_errors", attributes=attributes)
                log_event(
                    logger,
                    logging.INFO if response_status < 500 else logging.ERROR,
                    "http.request.completed",
                    method=scope.get("method", "UNKNOWN"),
                    route=route,
                    status_code=response_status,
                    response_started=response_started,
                    duration_ms=round(duration_ms, 3),
                )


def _route_template(scope: Scope) -> str:
    route: Any = scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else str(scope.get("path", "unknown"))
