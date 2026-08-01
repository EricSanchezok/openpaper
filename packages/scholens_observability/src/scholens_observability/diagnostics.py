"""Safe diagnostic snapshot contracts and deterministic sampling."""

from __future__ import annotations

import hashlib
import gzip
import json
import logging
import queue
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, TypeAlias
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

    def close(self, *, timeout: float = 0) -> None:
        del timeout


class ObjectStorageClient(Protocol):
    def put_object(self, **kwargs: Any) -> object: ...


class BufferedS3DiagnosticSnapshotRecorder:
    """Best-effort bounded snapshot writer; request handling never waits on S3."""

    def __init__(
        self,
        *,
        client: ObjectStorageClient,
        bucket: str,
        kms_key_id: str,
        prefix: str = "diagnostics",
        queue_capacity: int = 256,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._kms_key_id = kms_key_id
        self._prefix = prefix.strip("/")
        self._queue: queue.Queue[DiagnosticSnapshot | None] = queue.Queue(
            maxsize=queue_capacity
        )
        self._logger = logging.getLogger(__name__)
        self._thread = threading.Thread(
            target=self._run,
            name="diagnostic-snapshot-writer",
            daemon=True,
        )
        self._closed = False
        self._thread.start()

    def record(self, snapshot: DiagnosticSnapshot) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(snapshot)
        except queue.Full:
            self._logger.warning(
                "diagnostic.snapshot.dropped",
                extra={"reason": "writer_queue_full"},
            )

    def close(self, *, timeout: float = 5) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # The daemon writer will continue draining without blocking shutdown.
            return
        self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while True:
            snapshot = self._queue.get()
            try:
                if snapshot is None:
                    return
                self._write(snapshot)
            except Exception:
                self._logger.error(
                    "diagnostic.snapshot.write_failed",
                    exc_info=True,
                )
            finally:
                self._queue.task_done()

    def _write(self, snapshot: DiagnosticSnapshot) -> None:
        captured = snapshot.captured_at.astimezone(UTC)
        identity = snapshot.correlation_id or snapshot.request_id or "unscoped"
        key = (
            f"{self._prefix}/{captured:%Y/%m/%d}/{identity}/"
            f"{snapshot.service}/{snapshot.id}.json.gz"
        )
        payload = {
            "id": str(snapshot.id),
            "schema_version": snapshot.schema_version,
            "captured_at": snapshot.captured_at.isoformat(),
            "service": snapshot.service,
            "environment": snapshot.environment,
            "release": snapshot.release,
            "reason": snapshot.reason,
            "request_id": snapshot.request_id,
            "operation_id": snapshot.operation_id,
            "correlation_id": snapshot.correlation_id,
            "actor_id": snapshot.actor_id,
            "sections": snapshot.sections,
            "truncated": snapshot.truncated,
            "original_size_bytes": snapshot.original_size_bytes,
        }
        body = gzip.compress(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        )
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ContentEncoding="gzip",
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self._kms_key_id,
        )


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
