"""Jobs process composition for shared logs, traces and task metrics."""

from __future__ import annotations

import logging
import os
from time import monotonic
from typing import Any, Callable, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

import boto3
from celery import signals
from dotenv import load_dotenv
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from scholens_observability import (
    ObservabilityContext,
    BufferedS3DiagnosticSnapshotRecorder,
    DiagnosticSnapshotRecorder,
    NullDiagnosticSnapshotRecorder,
    add_counter,
    configure_logging,
    configure_telemetry,
    build_snapshot,
    current_context,
    log_event,
    record_histogram,
    set_context,
    should_sample_success,
)

load_dotenv()

logger = logging.getLogger(__name__)
_SERVICE = "scholens-jobs"
_ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
_RELEASE = os.getenv("RELEASE_SHA")
_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
_TASK_STARTS: dict[str, float] = {}
_CONFIGURED = False
_SIGNALS_CONNECTED = False
_DIAGNOSTIC_RECORDER: DiagnosticSnapshotRecorder = NullDiagnosticSnapshotRecorder()
_SUCCESS_SAMPLE_RATE = float(os.getenv("DIAGNOSTIC_SUCCESS_SAMPLE_RATE", "0.01"))


def _sanitize_dependency_url(value: object) -> str:
    parsed = urlsplit(str(value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _dependency_request_hook(span: Any, request: Any) -> None:
    sanitized = _sanitize_dependency_url(getattr(request, "url", ""))
    span.set_attribute("url.full", sanitized)
    span.set_attribute("url.query", "")
    span.set_attribute("http.url", sanitized)


async def _async_dependency_request_hook(span: Any, request: Any) -> None:
    _dependency_request_hook(span, request)


def _fastapi_request_hook(span: Any, scope: dict[str, Any]) -> None:
    span.set_attribute("url.full", str(scope.get("path", "/")))
    span.set_attribute("url.query", "")


def configure_jobs_observability() -> None:
    global _CONFIGURED, _DIAGNOSTIC_RECORDER
    if _CONFIGURED:
        return
    configure_logging(
        service=_SERVICE,
        environment=_ENVIRONMENT,
        release=_RELEASE,
    )
    configure_telemetry(
        service=_SERVICE,
        environment=_ENVIRONMENT,
        release=_RELEASE,
        endpoint=_OTLP_ENDPOINT,
    )
    if _OTLP_ENDPOINT:
        RequestsInstrumentor().instrument(request_hook=_dependency_request_hook)
        HTTPXClientInstrumentor().instrument(
            request_hook=_dependency_request_hook,
            async_request_hook=_async_dependency_request_hook,
        )
        celery_instrumentor = cast(Callable[[], Any], CeleryInstrumentor)()
        cast(Callable[[], object], celery_instrumentor.instrument)()
        redis_instrumentor = cast(Callable[[], Any], RedisInstrumentor)()
        cast(Callable[[], object], redis_instrumentor.instrument)()
    snapshot_bucket = os.getenv("DIAGNOSTIC_SNAPSHOT_BUCKET")
    snapshot_kms_key = os.getenv("DIAGNOSTIC_SNAPSHOT_KMS_KEY_ID")
    if snapshot_bucket and snapshot_kms_key:
        _DIAGNOSTIC_RECORDER = BufferedS3DiagnosticSnapshotRecorder(
            client=cast(Any, boto3.client("s3")),
            bucket=snapshot_bucket,
            kms_key_id=snapshot_kms_key,
        )
    elif _ENVIRONMENT.casefold() == "production":
        missing = (
            "DIAGNOSTIC_SNAPSHOT_KMS_KEY_ID"
            if snapshot_bucket
            else "DIAGNOSTIC_SNAPSHOT_BUCKET"
        )
        raise ValueError(f"{missing} is required in production")
    _connect_task_signals()
    _CONFIGURED = True


def instrument_jobs_api(application: Any) -> None:
    if _OTLP_ENDPOINT:
        FastAPIInstrumentor.instrument_app(
            application,
            server_request_hook=_fastapi_request_hook,
            excluded_urls="health",
        )


def _base_context(**fields: str | None) -> ObservabilityContext:
    return ObservabilityContext(
        service=_SERVICE,
        environment=_ENVIRONMENT,
        release=_RELEASE,
        **fields,
    )


def _task_header(task: Any, name: str) -> str | None:
    headers = getattr(getattr(task, "request", None), "headers", None)
    if not isinstance(headers, dict):
        return None
    value = headers.get(name)
    return str(value) if value is not None else None


def _connect_task_signals() -> None:
    global _SIGNALS_CONNECTED
    if _SIGNALS_CONNECTED:
        return
    signals.task_prerun.connect(_task_prerun, weak=False)
    signals.task_postrun.connect(_task_postrun, weak=False)
    signals.task_failure.connect(_task_failure, weak=False)
    signals.task_retry.connect(_task_retry, weak=False)
    signals.worker_ready.connect(_worker_ready, weak=False)
    signals.heartbeat_sent.connect(_heartbeat_sent, weak=False)
    signals.worker_shutdown.connect(_worker_shutdown, weak=False)
    _SIGNALS_CONNECTED = True


def _task_prerun(
    *,
    task_id: str | None = None,
    task: Any = None,
    **_kwargs: object,
) -> None:
    identifier = task_id or "unknown"
    task_name = str(getattr(task, "name", "unknown"))
    set_context(
        _base_context(
            operation_id=identifier,
            correlation_id=_task_header(task, "scholens-correlation-id"),
            causation_id=_task_header(task, "scholens-causation-id"),
            actor_id=_task_header(task, "scholens-actor-id"),
            task_id=identifier,
            component="celery",
            stage="execute",
        )
    )
    _TASK_STARTS[identifier] = monotonic()
    add_counter("scholens.jobs.started", attributes={"task_name": task_name})
    log_event(logger, logging.INFO, "job.task.started", task_name=task_name)


def _task_postrun(
    *,
    task_id: str | None = None,
    task: Any = None,
    state: str | None = None,
    **_kwargs: object,
) -> None:
    identifier = task_id or "unknown"
    task_name = str(getattr(task, "name", "unknown"))
    started = _TASK_STARTS.pop(identifier, None)
    duration_ms = (monotonic() - started) * 1000 if started is not None else 0.0
    attributes = {"task_name": task_name, "state": state or "unknown"}
    add_counter("scholens.jobs.completed", attributes=attributes)
    record_histogram("scholens.jobs.duration", duration_ms, attributes=attributes)
    log_event(
        logger,
        logging.INFO,
        "job.task.completed",
        task_name=task_name,
        state=state or "unknown",
        duration_ms=round(duration_ms, 3),
    )
    if state == "SUCCESS" and should_sample_success(
        identifier,
        rate=_SUCCESS_SAMPLE_RATE,
    ):
        _record_task_snapshot(
            snapshot_id=uuid4(),
            reason="job_success_sample",
            task_id=identifier,
            task_name=task_name,
            state=state,
        )
    set_context(_base_context())


def _task_failure(
    *,
    task_id: str | None = None,
    exception: BaseException | None = None,
    sender: Any = None,
    **_kwargs: object,
) -> None:
    identifier = task_id or "unknown"
    task_name = str(getattr(sender, "name", "unknown"))
    add_counter("scholens.jobs.failed", attributes={"task_name": task_name})
    snapshot_id = uuid4()
    _record_task_snapshot(
        snapshot_id=snapshot_id,
        reason="job_execution_failed",
        task_id=identifier,
        task_name=task_name,
        state="FAILURE",
        error_type=type(exception).__name__ if exception is not None else None,
    )
    log_event(
        logger,
        logging.ERROR,
        "job.task.failed",
        exc_info=exception,
        task_name=task_name,
        error_code="job_execution_failed",
        diagnostic_id=str(snapshot_id),
    )
    _TASK_STARTS.pop(identifier, None)


def _task_retry(
    *,
    request: Any = None,
    sender: Any = None,
    **_kwargs: object,
) -> None:
    task_name = str(getattr(sender, "name", "unknown"))
    add_counter("scholens.jobs.retried", attributes={"task_name": task_name})
    log_event(
        logger,
        logging.WARNING,
        "job.task.retried",
        task_name=task_name,
        retry_count=int(getattr(request, "retries", 0) or 0),
    )


def _worker_ready(*, sender: Any = None, **_kwargs: object) -> None:
    log_event(
        logger,
        logging.INFO,
        "job.worker.ready",
        worker=str(getattr(sender, "hostname", "unknown")),
    )


def _heartbeat_sent(**_kwargs: object) -> None:
    add_counter("scholens.jobs.worker_heartbeat")


def _record_task_snapshot(
    *,
    snapshot_id: UUID,
    reason: str,
    task_id: str,
    task_name: str,
    state: str | None,
    error_type: str | None = None,
) -> None:
    context = current_context()
    snapshot = build_snapshot(
        snapshot_id=snapshot_id,
        service=_SERVICE,
        environment=_ENVIRONMENT,
        release=_RELEASE,
        reason=reason,
        request_id=None,
        operation_id=context.operation_id,
        correlation_id=context.correlation_id,
        actor_id=context.actor_id,
        sections={
            "job": {
                "task_id": task_id,
                "task_name": task_name,
                "state": state,
                "error_type": error_type,
            }
        },
    )
    _DIAGNOSTIC_RECORDER.record(snapshot)


def _worker_shutdown(**_kwargs: object) -> None:
    close = getattr(_DIAGNOSTIC_RECORDER, "close", None)
    if callable(close):
        close(timeout=5)
