"""Pure Zotero connection and idempotent-import decisions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain.enums import JobStatus


class ImportReservationAction(str, Enum):
    EXECUTE = "execute"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class ImportReservationFacts:
    created: bool
    payload_matches: bool
    status: JobStatus
    result: dict[str, JsonValue] | None


def require_zotero_connected(*, connected: bool) -> None:
    if not connected:
        raise AppError(
            code="zotero_not_connected",
            message="Connect a Zotero account before using this feature",
            kind=FailureKind.INVALID_ARGUMENT,
        )


def canonical_import_payload(item_keys: list[str]) -> dict[str, JsonValue]:
    canonical_keys: list[JsonValue] = [key for key in sorted(item_keys)]
    return {"item_keys": canonical_keys}


def import_idempotency_key(*, actor_id: int, request_key: str) -> str:
    return f"zotero-import:{actor_id}:{request_key}"


def decide_import_reservation(
    facts: ImportReservationFacts,
) -> ImportReservationAction:
    if not facts.payload_matches:
        raise AppError(
            code="idempotency_key_reused",
            message="The Idempotency-Key was already used for another request",
            kind=FailureKind.CONFLICT,
        )
    if facts.created:
        return ImportReservationAction.EXECUTE
    if facts.status is JobStatus.COMPLETED and facts.result is not None:
        return ImportReservationAction.REPLAY
    raise AppError(
        code="idempotency_request_in_progress",
        message="The original request is still in progress",
        kind=FailureKind.CONFLICT,
    )
