"""Protocol-neutral public error metadata."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class ErrorEnvelope:
    code: str
    message: str
    kind: FailureKind
    retryable: bool
    stage: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    diagnostic_id: str | None = None
    details: dict[str, object] | None = None

    @classmethod
    def from_app_error(
        cls,
        error: AppError,
        *,
        stage: str | None,
        request_id: str | None,
        correlation_id: str | None,
        diagnostic_id: str | None,
    ) -> ErrorEnvelope:
        return cls(
            code=error.code,
            message=error.message,
            kind=error.kind,
            retryable=error.retryable,
            stage=stage,
            request_id=request_id,
            correlation_id=correlation_id,
            diagnostic_id=diagnostic_id,
            details=error.details,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "kind": self.kind.value,
            "retryable": self.retryable,
        }
        optional: dict[str, object | None] = {
            "stage": self.stage,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "diagnostic_id": self.diagnostic_id,
            "details": self.details,
        }
        payload.update({key: value for key, value in optional.items() if value is not None})
        return payload
