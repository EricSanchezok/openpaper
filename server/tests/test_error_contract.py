import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

from app.shared.domain import AppError, FailureKind
from app.transport.http.errors import (
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.transport.http.error_boundary import UnhandledErrorMiddleware
from app.transport.http.observability import RequestObservabilityMiddleware
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from scholens_observability import NullDiagnosticSnapshotRecorder
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/example",
            "headers": [],
            "query_string": b"",
            "server": ("internal.example", 8000),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
        }
    )


def _body(response: JSONResponse) -> dict[str, str]:
    parsed: dict[str, str] = json.loads(bytes(response.body))
    return parsed


def test_app_error_uses_stable_public_contract() -> None:
    response = asyncio.run(
        app_error_handler(
            _request(),
            AppError(
                code="jobs_service_unavailable",
                message="Processing is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            ),
        )
    )
    assert response.status_code == 503
    body = _body(response)
    assert body["code"] == "jobs_service_unavailable"
    assert body["message"] == "Processing is temporarily unavailable"
    assert body["kind"] == "unavailable"
    assert body["retryable"] is True
    UUID(body["diagnostic_id"])


def test_http_error_does_not_expose_arbitrary_detail() -> None:
    response = asyncio.run(
        http_error_handler(
            _request(),
            HTTPException(
                status_code=500,
                detail="connection failed for postgres://user:secret@db.internal/scholens",
            ),
        )
    )
    body = _body(response)
    assert body["code"] == "request_failed"
    assert body["message"] == "Request failed"
    assert body["kind"] == "internal"
    assert body["retryable"] is False
    UUID(body["diagnostic_id"])


def test_unhandled_error_does_not_expose_exception() -> None:
    response = asyncio.run(
        unhandled_error_handler(
            _request(),
            RuntimeError("redis://default:secret@redis.internal:6379/0"),
        )
    )
    assert response.status_code == 500
    body = _body(response)
    assert body["code"] == "internal_error"
    assert body["message"] == "An internal error occurred"
    assert body["kind"] == "internal"
    assert body["retryable"] is False
    UUID(body["diagnostic_id"])


def test_validation_error_uses_envelope_without_echoing_input() -> None:
    response = asyncio.run(
        validation_error_handler(
            _request(),
            RequestValidationError(
                [
                    {
                        "type": "string_too_short",
                        "loc": ("body", "api_key"),
                        "msg": "String should have at least 10 characters",
                        "input": "connector-secret-must-not-be-echoed",
                    }
                ]
            ),
        )
    )
    assert response.status_code == 422
    body = _body(response)
    assert body["code"] == "request_validation_failed"
    assert body["kind"] == "unprocessable"
    assert body["retryable"] is False
    assert "connector-secret-must-not-be-echoed" not in bytes(response.body).decode()


def test_unhandled_error_response_keeps_cors_and_request_identity() -> None:
    application = FastAPI()
    application.state.settings = SimpleNamespace(
        environment="test",
        release_sha="test",
    )
    application.state.diagnostic_snapshot_recorder = NullDiagnosticSnapshotRecorder()
    application.add_middleware(UnhandledErrorMiddleware)
    application.add_middleware(
        RequestObservabilityMiddleware,
        service="test-api",
        environment="test",
        release="test",
        success_sample_rate=0,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
        allow_credentials=True,
    )

    @application.get("/boom")
    async def boom() -> None:
        raise RuntimeError("database password must never reach the client")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get(
            "/boom",
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    UUID(response.headers["x-request-id"])
    assert response.json()["code"] == "internal_error"
    assert "password" not in response.text
