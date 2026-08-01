"""Configure logging, tracing and safe automatic instrumentation."""

from __future__ import annotations

from threading import Lock
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.bootstrap.settings import AppSettings
from app.database.database import engine
from fastapi import FastAPI
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from scholens_observability import configure_logging, configure_telemetry

_LOCK = Lock()
_DEPENDENCIES_INSTRUMENTED = False


def _sanitized_url(value: object) -> str:
    """Keep route-level dependency telemetry without query strings or fragments."""

    parsed = urlsplit(str(value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _requests_request_hook(span: Any, request: Any) -> None:
    sanitized = _sanitized_url(getattr(request, "url", ""))
    span.set_attribute("url.full", sanitized)
    span.set_attribute("http.url", sanitized)


def _httpx_request_hook(span: Any, request: Any) -> None:
    sanitized = _sanitized_url(getattr(request, "url", ""))
    span.set_attribute("url.full", sanitized)
    span.set_attribute("http.url", sanitized)


async def _httpx_async_request_hook(span: Any, request: Any) -> None:
    _httpx_request_hook(span, request)


def configure_application_observability(
    application: FastAPI,
    settings: AppSettings,
) -> None:
    configure_logging(
        service="scholens-api",
        environment=settings.environment,
        release=settings.release_sha,
    )
    configure_telemetry(
        service="scholens-api",
        environment=settings.environment,
        release=settings.release_sha,
        endpoint=settings.otel_exporter_otlp_endpoint,
    )
    if settings.otel_exporter_otlp_endpoint is None:
        return
    global _DEPENDENCIES_INSTRUMENTED
    with _LOCK:
        if not _DEPENDENCIES_INSTRUMENTED:
            RequestsInstrumentor().instrument(request_hook=_requests_request_hook)
            HTTPXClientInstrumentor().instrument(
                request_hook=_httpx_request_hook,
                async_request_hook=_httpx_async_request_hook,
            )
            SQLAlchemyInstrumentor().instrument(engine=engine)
            CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
            _DEPENDENCIES_INSTRUMENTED = True
    FastAPIInstrumentor.instrument_app(
        application,
        excluded_urls="livez,readyz",
    )
