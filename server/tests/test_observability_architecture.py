"""Executable safety rules for logs, telemetry, and diagnostics."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_RUNTIME_ROOTS = (
    ROOT / "server" / "app",
    ROOT / "jobs" / "src",
    ROOT / "packages" / "scholens_observability" / "src",
)
LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
EVENT_NAME = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


def _python_files() -> list[Path]:
    return [
        path
        for root in PYTHON_RUNTIME_ROOTS
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _is_runtime_logger_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute):
        return False
    owner = node.func.value
    return (
        isinstance(owner, ast.Name)
        and owner.id == "logger"
        or isinstance(owner, ast.Attribute)
        and owner.attr == "_logger"
    ) and node.func.attr in LOGGER_METHODS


def test_runtime_log_messages_are_literal_events_without_positional_payloads() -> None:
    violations: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_runtime_logger_call(node):
                continue
            if (
                len(node.args) != 1
                or not isinstance(node.args[0], ast.Constant)
                or not isinstance(node.args[0].value, str)
                or EVENT_NAME.fullmatch(node.args[0].value) is None
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_runtime_does_not_reintroduce_known_raw_payload_logs() -> None:
    forbidden = (
        "Response JSON:",
        "Constructed URL:",
        "received chunks:",
        "with key: {object_key}",
        "connector_api_key",
    )
    violations: list[str] = []
    for path in _python_files():
        source = path.read_text()
        for marker in forbidden:
            if marker in source:
                violations.append(f"{path.relative_to(ROOT)}: {marker}")
    assert violations == []


def test_outbound_http_auto_instrumentation_sanitizes_urls() -> None:
    server_runtime = (ROOT / "server/app/observability/runtime.py").read_text()
    jobs_runtime = (ROOT / "jobs/src/observability.py").read_text()
    for source in (server_runtime, jobs_runtime):
        assert "urlunsplit((parsed.scheme, parsed.netloc, parsed.path" in source
        assert 'span.set_attribute("url.query", "")' in source
        assert "request_hook=" in source
        assert "server_request_hook=" in source
        assert "RedisInstrumentor" in source


def test_technical_observability_has_no_database_model() -> None:
    model_sources = "\n".join(
        path.read_text()
        for path in (ROOT / "server/app/database").rglob("*.py")
    )
    for forbidden_name in (
        "DiagnosticSnapshotModel",
        "ApplicationLogModel",
        "TraceModel",
        "ErrorEventModel",
    ):
        assert forbidden_name not in model_sources
    assert not (ROOT / "server/app/database/telemetry.py").exists()
    assert (ROOT / "server/app/database/product_analytics.py").exists()


def test_cors_exposes_correlation_headers_for_credentialed_requests() -> None:
    app_factory = (ROOT / "server/app/bootstrap/app_factory.py").read_text()
    assert '"X-Request-ID"' in app_factory
    assert '"X-Correlation-ID"' in app_factory
    assert 'expose_headers=["*"]' not in app_factory
    request_middleware = app_factory.rindex(
        "application.add_middleware(\n        RequestObservabilityMiddleware"
    )
    assert request_middleware < app_factory.rindex(
        "configure_application_observability(application, runtime_settings)"
    )
