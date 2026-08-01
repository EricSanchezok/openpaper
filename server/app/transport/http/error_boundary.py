"""Outermost application error ownership before protocol middleware unwinds."""

from __future__ import annotations

from app.transport.http.errors import unhandled_error_handler
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UnhandledErrorMiddleware:
    """Turn unknown application failures into the canonical error envelope.

    This middleware intentionally sits inside CORS and request observability so
    pre-response failures receive the same headers as every other response.
    Failures after response headers started are recorded, then re-raised because
    HTTP can no longer replace the partial stream with a JSON error response.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        response_started = False

        async def track_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, track_start)
        except Exception as exc:
            response = await unhandled_error_handler(
                Request(scope, receive=receive),
                exc,
            )
            if response_started:
                scope.setdefault("state", {})["stream_failed"] = True
                raise
            await response(scope, receive, send)


__all__ = ["UnhandledErrorMiddleware"]
