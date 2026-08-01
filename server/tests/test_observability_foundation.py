from __future__ import annotations

import json
import logging
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from scholens_observability import (
    ObservabilityContext,
    SensitiveValue,
    bind_context,
    build_snapshot,
    configure_logging,
    current_context,
    diagnostic_id,
    log_event,
    set_context,
    should_sample_success,
)

from app.transport.http.observability import RequestObservabilityMiddleware


def test_context_is_scoped_and_restored() -> None:
    set_context(ObservabilityContext(service="test", environment="test"))
    with bind_context(request_id="request-1", component="chat"):
        assert current_context().request_id == "request-1"
        assert current_context().component == "chat"
    assert current_context().request_id is None
    assert current_context().component is None


def test_structured_logging_drops_security_fields(capsys: pytest.CaptureFixture[str]) -> None:
    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        configure_logging(service="test", environment="production")
        logger = logging.getLogger("tests.observability")
        log_event(
            logger,
            logging.ERROR,
            "test.failure",
            api_key="must-not-appear",
            safe_identifier="visible",
            exc_info=RuntimeError("postgres://user:secret@example.invalid/db"),
        )
        output = capsys.readouterr().out.strip()
        payload = json.loads(output)
        assert payload["event"] == "test.failure"
        assert payload["safe_identifier"] == "visible"
        assert payload["exception_type"] == "RuntimeError"
        assert "must-not-appear" not in output
        assert "postgres://" not in output
    finally:
        root.handlers.clear()
        root.handlers.extend(previous_handlers)
        root.setLevel(previous_level)


def test_diagnostic_snapshot_rejects_credentials() -> None:
    with pytest.raises(ValueError, match="Security-sensitive"):
        build_snapshot(
            snapshot_id=diagnostic_id(),
            service="api",
            environment="test",
            release=None,
            reason="test",
            request_id=None,
            operation_id=None,
            correlation_id=None,
            actor_id=None,
            sections={"request": {"connector_api_key": "secret"}},
        )
    with pytest.raises(ValueError, match="Sensitive value"):
        build_snapshot(
            snapshot_id=diagnostic_id(),
            service="api",
            environment="test",
            release=None,
            reason="test",
            request_id=None,
            operation_id=None,
            correlation_id=None,
            actor_id=None,
            sections={"request": {"value": SensitiveValue("secret")}},
        )


def test_success_sampling_is_deterministic() -> None:
    correlation_id = uuid4()
    values = {
        should_sample_success(correlation_id, rate=0.5)
        for _ in range(10)
    }
    assert len(values) == 1


def test_request_middleware_assigns_trusted_request_id() -> None:
    app = FastAPI()
    app.add_middleware(
        RequestObservabilityMiddleware,
        service="test-api",
        environment="test",
        release=None,
    )

    @app.get("/items/{item_id}")
    def item(item_id: str, request: Request) -> dict[str, str]:
        request.state.correlation_id = str(UUID(int=1))
        return {"item_id": item_id, "request_id": request.state.request_id}

    with TestClient(app) as client:
        response = client.get(
            "/items/example",
            headers={"X-Request-ID": str(UUID(int=2))},
        )

    assert response.status_code == 200
    response_id = response.headers["X-Request-ID"]
    UUID(response_id)
    assert response_id != str(UUID(int=2))
    assert response.json()["request_id"] == response_id
    assert response.headers["X-Correlation-ID"] == str(UUID(int=1))
