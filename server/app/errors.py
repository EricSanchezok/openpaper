"""Compatibility import removed after callers migrate to shared/transport layers."""

from app.shared.domain import AppError
from app.transport.http.errors import (
    ApiErrorResponse,
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
)

__all__ = [
    "ApiErrorResponse",
    "AppError",
    "app_error_handler",
    "http_error_handler",
    "unhandled_error_handler",
]
