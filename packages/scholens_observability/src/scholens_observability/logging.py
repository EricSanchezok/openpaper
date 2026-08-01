"""Structured logging with context and fail-closed credential filtering."""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from datetime import UTC, datetime
from opentelemetry import trace

from .context import ObservabilityContext, current_context, set_context

_STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__)
_SECURITY_FIELD_FRAGMENTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "credential",
    "private_key",
    "signature",
    "connection_string",
    "database_url",
)
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:authorization|cookie|password|secret|api[_-]?key|access[_-]?key|"
    r"session[_-]?token|refresh[_-]?token)\b\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"
)
_JWT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\."
    r"[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])"
)


def _redact_string(value: str) -> str:
    redacted = _INLINE_SECRET_PATTERN.sub("[REDACTED]", value)
    return _JWT_PATTERN.sub("[REDACTED_JWT]", redacted)


def _trace_fields() -> dict[str, str]:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}
    return {
        "trace_id": format(span_context.trace_id, "032x"),
        "span_id": format(span_context.span_id, "016x"),
    }


def _safe_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return not any(fragment in normalized for fragment in _SECURITY_FIELD_FRAGMENTS)


def _safe_value(value: object) -> object:
    if isinstance(value, str):
        return _redact_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if _safe_key(str(key))
        }
    # Arbitrary object stringification can invoke custom repr/str methods or
    # expose exception messages containing URLs and credentials. Callers must
    # deliberately project business objects into safe scalar fields.
    return f"<{type(value).__name__}>"


class StructuredFormatter(logging.Formatter):
    def __init__(self, *, json_output: bool) -> None:
        super().__init__()
        self._json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        event = _redact_string(
            str(getattr(record, "event", None) or record.getMessage())
        )
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": record.levelname,
            "event": str(event),
            **current_context().fields(),
            **_trace_fields(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key in {"event", "message", "asctime"}:
                continue
            if _safe_key(key):
                payload[key] = _safe_value(value)
        if record.exc_info is not None:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["exception_type"] = exc_type.__name__ if exc_type else "Exception"
            del exc_value
            # Exception messages frequently embed URLs, remote payloads or
            # credentials. Preserve code locations and exception types while
            # deliberately excluding the raw message.
            payload["exception_stack"] = "".join(
                traceback.format_list(traceback.extract_tb(exc_tb))
            ).rstrip()
        if self._json_output:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        identifiers = " ".join(
            f"{key}={payload[key]}"
            for key in ("request_id", "correlation_id", "trace_id")
            if key in payload
        )
        suffix = f" [{identifiers}]" if identifiers else ""
        details = {
            key: value
            for key, value in payload.items()
            if key
            not in {
                "timestamp",
                "severity",
                "event",
                "service",
                "environment",
                "release",
                "request_id",
                "correlation_id",
                "trace_id",
                "span_id",
            }
        }
        rendered_details = f" {details}" if details else ""
        return f"{payload['timestamp']} {record.levelname:<8} {event}{suffix}{rendered_details}"


def configure_logging(
    *,
    service: str,
    environment: str,
    release: str | None = None,
    level: int = logging.INFO,
) -> None:
    set_context(
        ObservabilityContext(
            service=service,
            environment=environment,
            release=release,
        )
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        StructuredFormatter(json_output=environment.casefold() == "production")
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    for noisy_logger in ("httpcore", "httpx", "urllib3", "botocore", "boto3"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    exc_info: BaseException | None = None,
    **fields: object,
) -> None:
    exception_tuple = None
    if exc_info is not None:
        exception_tuple = (type(exc_info), exc_info, exc_info.__traceback__)
    logger.log(level, event, extra={"event": event, **fields}, exc_info=exception_tuple)
