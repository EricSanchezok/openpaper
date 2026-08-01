"""Stable application failures independent of every inbound protocol."""

from __future__ import annotations

from enum import Enum


class FailureKind(str, Enum):
    """Protocol-neutral failure categories.

    A transport maps these categories to its own status vocabulary.  Error
    codes remain the stable, product-specific contract.
    """

    INVALID_ARGUMENT = "invalid_argument"
    UNAUTHENTICATED = "unauthenticated"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNPROCESSABLE = "unprocessable"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_FAILURE = "dependency_failure"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        kind: FailureKind,
        details: dict[str, object] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.message = message
        self.kind = kind
        self.details = details
        self.retryable = (
            retryable
            if retryable is not None
            else kind
            in {
                FailureKind.RATE_LIMITED,
                FailureKind.DEPENDENCY_FAILURE,
                FailureKind.UNAVAILABLE,
            }
        )
