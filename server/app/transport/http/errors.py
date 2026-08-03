"""Stable HTTP error representation for every API surface."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.shared.domain import AppError, FailureKind
from app.observability.diagnostics import record_http_diagnostic
from fastapi.exceptions import RequestValidationError
from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from scholens_observability import add_counter, current_context, log_event
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

FAILURE_HTTP_STATUS = {
    FailureKind.INVALID_ARGUMENT: 400,
    FailureKind.UNAUTHENTICATED: 401,
    FailureKind.PERMISSION_DENIED: 403,
    FailureKind.NOT_FOUND: 404,
    FailureKind.CONFLICT: 409,
    FailureKind.PAYLOAD_TOO_LARGE: 413,
    FailureKind.UNPROCESSABLE: 422,
    FailureKind.RATE_LIMITED: 429,
    FailureKind.DEPENDENCY_FAILURE: 502,
    FailureKind.UNAVAILABLE: 503,
    FailureKind.INTERNAL: 500,
}


class ApiErrorResponse(BaseModel):
    code: str
    message: str
    kind: FailureKind
    retryable: bool
    stage: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    diagnostic_id: str | None = None
    details: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class _DiagnosticFields:
    stage: str | None
    request_id: str | None
    correlation_id: str | None
    diagnostic_id: str | None


@dataclass(frozen=True, slots=True)
class _NormalizedHttpError:
    status_code: int
    detail: Mapping[str, object] | str
    headers: Mapping[str, str] | None


def _kind_for_status(status_code: int) -> FailureKind:
    if status_code == 401:
        return FailureKind.UNAUTHENTICATED
    if status_code == 403:
        return FailureKind.PERMISSION_DENIED
    if status_code == 404:
        return FailureKind.NOT_FOUND
    if status_code == 409:
        return FailureKind.CONFLICT
    if status_code == 413:
        return FailureKind.PAYLOAD_TOO_LARGE
    if status_code == 422:
        return FailureKind.UNPROCESSABLE
    if status_code == 429:
        return FailureKind.RATE_LIMITED
    if status_code == 502:
        return FailureKind.DEPENDENCY_FAILURE
    if status_code == 503:
        return FailureKind.UNAVAILABLE
    if status_code >= 500:
        return FailureKind.INTERNAL
    return FailureKind.INVALID_ARGUMENT


def _auth_error(
    *,
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> _NormalizedHttpError:
    return _NormalizedHttpError(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers=headers,
    )


def _normalize_http_error(
    request: Request,
    exc: HTTPException,
) -> _NormalizedHttpError:
    """Translate provider-specific auth failures at the public HTTP boundary."""

    path = request.url.path.rstrip("/")
    headers = dict(exc.headers or {})
    detail_text = str(exc.detail).lower()

    if path == "/api/v1/me" and exc.status_code in {401, 403}:
        return _auth_error(
            status_code=401,
            code="auth_token_invalid_or_expired",
            message="Authentication is required",
            headers=headers,
        )

    prefix = "/api/v1/auth/"
    if not path.startswith(prefix):
        return _NormalizedHttpError(exc.status_code, exc.detail, exc.headers)

    endpoint = path.removeprefix(prefix)
    if exc.status_code == 429:
        headers.setdefault("Retry-After", "60")
        return _auth_error(
            status_code=429,
            code="auth_rate_limited",
            message="Too many authentication attempts",
            headers=headers,
        )
    if exc.status_code >= 500:
        headers.setdefault("Retry-After", "5")
        return _auth_error(
            status_code=503,
            code="auth_service_unavailable",
            message="Authentication is temporarily unavailable",
            headers=headers,
        )
    if endpoint == "login" and exc.status_code in {400, 401, 403, 404}:
        return _auth_error(
            status_code=401,
            code="auth_invalid_credentials",
            message="Invalid email or password",
            headers=headers,
        )
    if endpoint == "refresh" and exc.status_code in {400, 401, 403, 404}:
        code = (
            "auth_session_missing"
            if "missing" in detail_text
            else "auth_session_expired"
        )
        return _auth_error(
            status_code=401,
            code=code,
            message="The session is unavailable",
            headers=headers,
        )
    if endpoint == "verify-email" and exc.status_code in {400, 401, 404}:
        return _auth_error(
            status_code=400,
            code="auth_verification_token_invalid",
            message="The verification link is invalid or expired",
            headers=headers,
        )
    if endpoint == "reset-password" and exc.status_code in {400, 401, 404}:
        return _auth_error(
            status_code=400,
            code="auth_reset_token_invalid",
            message="The reset link is invalid or expired",
            headers=headers,
        )
    if exc.status_code in {401, 403}:
        return _auth_error(
            status_code=401,
            code="auth_token_invalid_or_expired",
            message="Authentication is required",
            headers=headers,
        )
    return _NormalizedHttpError(exc.status_code, exc.detail, exc.headers)


def _retryable(kind: FailureKind) -> bool:
    return kind in {
        FailureKind.RATE_LIMITED,
        FailureKind.DEPENDENCY_FAILURE,
        FailureKind.UNAVAILABLE,
    }


def _diagnostic_fields(
    request: Request,
    *,
    status_code: int,
) -> _DiagnosticFields:
    context = current_context()
    authenticated = bool(getattr(request.state, "authenticated", False))
    return _DiagnosticFields(
        stage=context.stage,
        request_id=getattr(request.state, "request_id", context.request_id),
        correlation_id=getattr(
            request.state,
            "correlation_id",
            context.correlation_id,
        ),
        diagnostic_id=(str(uuid4()) if authenticated or status_code >= 500 else None),
    )


def _record_diagnostic(
    request: Request,
    *,
    fields: _DiagnosticFields,
    reason: str,
    error_code: str,
    error_kind: FailureKind,
    status_code: int,
) -> None:
    if fields.diagnostic_id is None:
        return
    try:
        record_http_diagnostic(
            request,
            snapshot_id=UUID(fields.diagnostic_id),
            reason=reason,
            error_code=error_code,
            error_kind=error_kind.value,
            status_code=status_code,
        )
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "diagnostic.snapshot.capture_failed",
            exc_info=exc,
            diagnostic_id=fields.diagnostic_id,
        )


def _http_error_payload(
    request: Request,
    exc: _NormalizedHttpError,
) -> ApiErrorResponse:
    kind = _kind_for_status(exc.status_code)
    fields = _diagnostic_fields(request, status_code=exc.status_code)
    if isinstance(exc.detail, Mapping):
        code = str(exc.detail.get("code") or "request_failed")
        message = str(exc.detail.get("message") or code.replace("_", " "))
        details = exc.detail.get("details")
        return ApiErrorResponse(
            code=code,
            message=message,
            kind=kind,
            retryable=_retryable(kind),
            details=dict(details) if isinstance(details, Mapping) else None,
            stage=fields.stage,
            request_id=fields.request_id,
            correlation_id=fields.correlation_id,
            diagnostic_id=fields.diagnostic_id,
        )
    if isinstance(exc.detail, str):
        detail = exc.detail
        if detail.isidentifier() and detail.islower():
            return ApiErrorResponse(
                code=detail,
                message=detail.replace("_", " "),
                kind=kind,
                retryable=_retryable(kind),
                stage=fields.stage,
                request_id=fields.request_id,
                correlation_id=fields.correlation_id,
                diagnostic_id=fields.diagnostic_id,
            )
    return ApiErrorResponse(
        code="request_failed",
        message="Request failed",
        kind=kind,
        retryable=_retryable(kind),
        stage=fields.stage,
        request_id=fields.request_id,
        correlation_id=fields.correlation_id,
        diagnostic_id=fields.diagnostic_id,
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise TypeError("app_error_handler received an unexpected exception")
    status_code = FAILURE_HTTP_STATUS[exc.kind]
    fields = _diagnostic_fields(request, status_code=status_code)
    payload = ApiErrorResponse(
        code=exc.code,
        message=exc.message,
        kind=exc.kind,
        retryable=exc.retryable,
        details=exc.details,
        stage=fields.stage,
        request_id=fields.request_id,
        correlation_id=fields.correlation_id,
        diagnostic_id=fields.diagnostic_id,
    )
    _record_diagnostic(
        request,
        fields=fields,
        reason="http_application_error",
        error_code=exc.code,
        error_kind=exc.kind,
        status_code=status_code,
    )
    add_counter(
        "scholens.errors",
        attributes={"code": exc.code, "kind": exc.kind.value},
    )
    log_event(
        logger,
        logging.WARNING if status_code < 500 else logging.ERROR,
        "http.application_error",
        error_code=exc.code,
        error_kind=exc.kind.value,
        retryable=exc.retryable,
        status_code=status_code,
        diagnostic_id=payload.diagnostic_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, HTTPException):
        raise TypeError("http_error_handler received an unexpected exception")
    normalized = _normalize_http_error(request, exc)
    payload = _http_error_payload(request, normalized)
    fields = _DiagnosticFields(
        stage=payload.stage,
        request_id=payload.request_id,
        correlation_id=payload.correlation_id,
        diagnostic_id=payload.diagnostic_id,
    )
    _record_diagnostic(
        request,
        fields=fields,
        reason="http_protocol_error",
        error_code=payload.code,
        error_kind=payload.kind,
        status_code=normalized.status_code,
    )
    add_counter(
        "scholens.errors",
        attributes={"code": payload.code, "kind": payload.kind.value},
    )
    log_event(
        logger,
        logging.WARNING if normalized.status_code < 500 else logging.ERROR,
        "http.protocol_error",
        error_code=payload.code,
        error_kind=payload.kind.value,
        retryable=payload.retryable,
        status_code=normalized.status_code,
        diagnostic_id=payload.diagnostic_id,
    )
    return JSONResponse(
        status_code=normalized.status_code,
        content=payload.model_dump(exclude_none=True),
        headers=normalized.headers,
    )


async def validation_error_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError("validation_error_handler received an unexpected exception")
    fields = _diagnostic_fields(request, status_code=422)
    errors = [
        {
            "type": str(error.get("type", "validation_error")),
            "location": [str(part) for part in error.get("loc", ())],
        }
        for error in exc.errors()
    ]
    is_auth_request = request.url.path.startswith("/api/v1/auth/")
    payload = ApiErrorResponse(
        code="validation_error" if is_auth_request else "request_validation_failed",
        message="The request data is invalid",
        kind=FailureKind.UNPROCESSABLE,
        retryable=False,
        stage=fields.stage,
        request_id=fields.request_id,
        correlation_id=fields.correlation_id,
        diagnostic_id=fields.diagnostic_id,
        details={"errors": errors},
    )
    _record_diagnostic(
        request,
        fields=fields,
        reason="http_validation_error",
        error_code=payload.code,
        error_kind=payload.kind,
        status_code=422,
    )
    add_counter(
        "scholens.errors",
        attributes={"code": payload.code, "kind": payload.kind.value},
    )
    log_event(
        logger,
        logging.WARNING,
        "http.validation_error",
        error_code=payload.code,
        error_kind=payload.kind.value,
        retryable=False,
        status_code=422,
        validation_error_count=len(errors),
        diagnostic_id=payload.diagnostic_id,
    )
    return JSONResponse(
        status_code=422,
        content=payload.model_dump(exclude_none=True),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    fields = _diagnostic_fields(request, status_code=500)
    _record_diagnostic(
        request,
        fields=fields,
        reason="http_unhandled_error",
        error_code="internal_error",
        error_kind=FailureKind.INTERNAL,
        status_code=500,
    )
    add_counter(
        "scholens.errors",
        attributes={"code": "internal_error", "kind": FailureKind.INTERNAL.value},
    )
    log_event(
        logger,
        logging.ERROR,
        "http.unhandled_error",
        exc_info=exc,
        method=request.method,
        route=(str(getattr(request.scope.get("route"), "path", request.url.path))),
        error_code="internal_error",
        error_kind=FailureKind.INTERNAL.value,
        retryable=False,
        diagnostic_id=fields.diagnostic_id,
    )
    payload = ApiErrorResponse(
        code="internal_error",
        message="An internal error occurred",
        kind=FailureKind.INTERNAL,
        retryable=False,
        stage=fields.stage,
        request_id=fields.request_id,
        correlation_id=fields.correlation_id,
        diagnostic_id=fields.diagnostic_id,
    )
    return JSONResponse(
        status_code=500,
        content=payload.model_dump(exclude_none=True),
    )
