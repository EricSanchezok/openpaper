"""Stable HTTP error representation for every API surface."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from app.shared.domain import AppError, FailureKind
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

FAILURE_HTTP_STATUS = {
    FailureKind.INVALID_ARGUMENT: 400,
    FailureKind.UNAUTHENTICATED: 401,
    FailureKind.PERMISSION_DENIED: 403,
    FailureKind.NOT_FOUND: 404,
    FailureKind.CONFLICT: 409,
    FailureKind.UNPROCESSABLE: 422,
    FailureKind.RATE_LIMITED: 429,
    FailureKind.DEPENDENCY_FAILURE: 502,
    FailureKind.UNAVAILABLE: 503,
    FailureKind.INTERNAL: 500,
}


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, object] | None = None


def _http_error_payload(exc: HTTPException) -> ApiErrorResponse:
    if isinstance(exc.detail, Mapping):
        code = str(exc.detail.get("code") or "request_failed")
        message = str(exc.detail.get("message") or code.replace("_", " "))
        return ApiErrorResponse(code=code, message=message)
    if isinstance(exc.detail, str):
        detail = exc.detail
        if detail.isidentifier() and detail.islower():
            return ApiErrorResponse(code=detail, message=detail.replace("_", " "))
    return ApiErrorResponse(code="request_failed", message="Request failed")


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise TypeError("app_error_handler received an unexpected exception")
    payload = ApiErrorResponse(
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )
    return JSONResponse(
        status_code=FAILURE_HTTP_STATUS[exc.kind],
        content=payload.model_dump(exclude_none=True),
    )


async def http_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise TypeError("http_error_handler received an unexpected exception")
    payload = _http_error_payload(exc)
    return JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(exclude_none=True),
        headers=exc.headers,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "Unhandled API error for %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    payload = ApiErrorResponse(
        code="internal_error",
        message="An internal error occurred",
    )
    return JSONResponse(
        status_code=500,
        content=payload.model_dump(exclude_none=True),
    )
