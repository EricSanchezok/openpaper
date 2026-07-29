"""Pure paper-ingestion identity and request rules."""

from __future__ import annotations

import hashlib

from app.shared.domain import AppError, FailureKind

MAX_PDF_SIZE_MB = 30
MAX_PDF_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024
MAX_IDEMPOTENCY_KEY_LENGTH = 200


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise AppError(
            code="invalid_idempotency_key",
            message="Idempotency-Key must contain between 1 and 200 characters",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    return normalized


def durable_ingestion_key(
    *,
    actor_id: int,
    project_id: object | None,
    idempotency_key: str | None,
) -> str | None:
    if idempotency_key is None:
        return None
    scope = str(project_id) if project_id is not None else "library"
    return f"pdf-ingestion:{actor_id}:{scope}:{idempotency_key}"
