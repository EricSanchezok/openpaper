"""Safe diagnostic snapshot contracts and deterministic sampling."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeAlias
from uuid import UUID, uuid4

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_FORBIDDEN_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "credential",
    "private_key",
    "signature",
    "database_url",
    "connection_string",
)
_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SensitiveValue:
    """Marks a value that must never enter diagnostics or logs."""

    value: str

    def __repr__(self) -> str:
        return "SensitiveValue(***)"


@dataclass(frozen=True, slots=True)
class DiagnosticSnapshot:
    id: UUID
    schema_version: int
    captured_at: datetime
    service: str
    environment: str
    release: str | None
    reason: str
    request_id: str | None
    operation_id: str | None
    correlation_id: str | None
    actor_id: str | None
    sections: dict[str, JsonValue]
    truncated: bool
    original_size_bytes: int


class DiagnosticSnapshotRecorder(Protocol):
    def record(self, snapshot: DiagnosticSnapshot) -> None: ...


class NullDiagnosticSnapshotRecorder:
    def record(self, snapshot: DiagnosticSnapshot) -> None:
        del snapshot


def diagnostic_id() -> UUID:
    return uuid4()


def should_sample_success(correlation_id: UUID | str, *, rate: float = 0.01) -> bool:
    if not 0 <= rate <= 1:
        raise ValueError("diagnostic sample rate must be between zero and one")
    digest = hashlib.sha256(str(correlation_id).encode()).digest()
    sample = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
    return sample < rate


def _is_forbidden_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in _FORBIDDEN_KEY_PARTS)


def _validate(value: object, *, path: str) -> JsonValue:
    if isinstance(value, SensitiveValue):
        raise ValueError(f"Sensitive value rejected at {path}")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_validate(item, path=f"{path}[]") for item in value]
    if isinstance(value, dict):
        validated: dict[str, JsonValue] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if _is_forbidden_key(key):
                raise ValueError(f"Security-sensitive diagnostic key rejected at {path}.{key}")
            validated[key] = _validate(item, path=f"{path}.{key}")
        return validated
    raise TypeError(f"Unsupported diagnostic value at {path}: {type(value).__name__}")


def build_snapshot(
    *,
    snapshot_id: UUID,
    service: str,
    environment: str,
    release: str | None,
    reason: str,
    request_id: str | None,
    operation_id: str | None,
    correlation_id: str | None,
    actor_id: str | None,
    sections: dict[str, object],
) -> DiagnosticSnapshot:
    validated = _validate(sections, path="sections")
    if not isinstance(validated, dict):
        raise TypeError("Diagnostic sections must be an object")
    encoded = json.dumps(validated, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > _MAX_UNCOMPRESSED_BYTES:
        manifest: dict[str, JsonValue] = {
            "capture_truncated": True,
            "original_size_bytes": len(encoded),
            "content_sha256": hashlib.sha256(encoded).hexdigest(),
            "section_sizes": {
                key: len(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
                )
                for key, value in validated.items()
            },
        }
        validated = manifest
        truncated = True
    else:
        truncated = False
    return DiagnosticSnapshot(
        id=snapshot_id,
        schema_version=1,
        captured_at=datetime.now(UTC),
        service=service,
        environment=environment,
        release=release,
        reason=reason,
        request_id=request_id,
        operation_id=operation_id,
        correlation_id=correlation_id,
        actor_id=actor_id,
        sections=validated,
        truncated=truncated,
        original_size_bytes=len(encoded),
    )
