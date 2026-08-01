"""Configure logging, tracing and safe automatic instrumentation."""

from __future__ import annotations

from threading import Lock

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
            RequestsInstrumentor().instrument()
            HTTPXClientInstrumentor().instrument()
            SQLAlchemyInstrumentor().instrument(engine=engine)
            CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
            _DEPENDENCIES_INSTRUMENTED = True
    FastAPIInstrumentor.instrument_app(
        application,
        excluded_urls="livez,readyz",
    )
