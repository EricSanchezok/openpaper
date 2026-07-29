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
    UNPROCESSABLE = "unprocessable"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_FAILURE = "dependency_failure"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


_LEGACY_STATUS_KINDS = {
    400: FailureKind.INVALID_ARGUMENT,
    401: FailureKind.UNAUTHENTICATED,
    403: FailureKind.PERMISSION_DENIED,
    404: FailureKind.NOT_FOUND,
    409: FailureKind.CONFLICT,
    413: FailureKind.INVALID_ARGUMENT,
    422: FailureKind.UNPROCESSABLE,
    429: FailureKind.RATE_LIMITED,
    500: FailureKind.INTERNAL,
    502: FailureKind.DEPENDENCY_FAILURE,
    503: FailureKind.UNAVAILABLE,
}


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        kind: FailureKind | None = None,
        details: dict[str, object] | None = None,
        # Transitional compatibility while existing call sites are migrated in
        # domain-sized batches. Removed by the final architecture cleanup.
        status_code: int | None = None,
    ) -> None:
        if (kind is None) == (status_code is None):
            raise TypeError("Exactly one of kind or status_code is required")
        if kind is None:
            assert status_code is not None
            try:
                kind = _LEGACY_STATUS_KINDS[status_code]
            except KeyError as exc:
                raise ValueError(
                    f"Unsupported legacy application status: {status_code}"
                ) from exc
        super().__init__(code)
        self.code = code
        self.message = message
        self.kind = kind
        self.details = details
