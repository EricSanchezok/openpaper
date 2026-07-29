import asyncio
import json

from app.shared.domain import AppError
from app.transport.http.errors import (
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
)
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
                status_code=503,
            ),
        )
    )
    assert response.status_code == 503
    assert _body(response) == {
        "code": "jobs_service_unavailable",
        "message": "Processing is temporarily unavailable",
    }


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
    assert _body(response) == {
        "code": "request_failed",
        "message": "Request failed",
    }


def test_unhandled_error_does_not_expose_exception() -> None:
    response = asyncio.run(
        unhandled_error_handler(
            _request(),
            RuntimeError("redis://default:secret@redis.internal:6379/0"),
        )
    )
    assert response.status_code == 500
    assert _body(response) == {
        "code": "internal_error",
        "message": "An internal error occurred",
    }
