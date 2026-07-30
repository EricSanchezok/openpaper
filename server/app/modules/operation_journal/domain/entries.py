"""Immutable values written to the append-only operation journal."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

_ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}\.[a-z][a-z0-9_]{0,62}$")
_RESOURCE_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/~-]{0,254}$")
_SAFE_PROJECTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}$")
_DIGEST_REFERENCE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_ORIGIN_KINDS = frozenset(
    {
        "http",
        "conversation",
        "mcp",
        "job",
        "webhook",
        "oauth_callback",
        "scheduler",
    }
)
_INITIATORS = frozenset({"user", "agent", "system"})
_CREDENTIAL_KINDS = frozenset(
    {
        "cloud_session",
        "access_key",
        "internal_signature",
        "provider_signature",
    }
)
MAX_RESOURCE_REFS = 100


class OperationAction(str):
    """Validated, stable business-change identifier."""

    def __new__(cls, value: str) -> OperationAction:
        if not isinstance(value, str) or _ACTION_PATTERN.fullmatch(value) is None:
            raise ValueError("operation action must use lower_snake.lower_snake format")
        return str.__new__(cls, value)


@dataclass(frozen=True, slots=True, order=True)
class ResourceRef:
    type: str
    id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.type, str)
            or _RESOURCE_TYPE_PATTERN.fullmatch(self.type) is None
        ):
            raise ValueError("resource type must be normalized lower_snake")
        if (
            not isinstance(self.id, str)
            or _RESOURCE_ID_PATTERN.fullmatch(self.id) is None
        ):
            raise ValueError("resource id must be a normalized bounded identifier")


@dataclass(frozen=True, slots=True)
class OperationChange:
    action: OperationAction
    resources: tuple[ResourceRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.action, OperationAction):
            raise TypeError("operation change action must be an OperationAction")
        object.__setattr__(self, "resources", _normalize_resources(self.resources))


@dataclass(frozen=True, slots=True)
class OperationJournalEntry:
    entry_id: UUID
    operation_id: UUID
    correlation_id: UUID
    causation_id: UUID | None
    actor_id: int | None
    initiated_by: str
    origin_kind: str
    origin_name: str | None
    origin_reference: str | None
    credential_kind: str | None
    credential_id: str | None
    request_id: UUID | None
    conversation_id: UUID | None
    turn_id: UUID | None
    job_id: UUID | None
    action: OperationAction
    resources: tuple[ResourceRef, ...]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.entry_id, field_name="entry_id")
        _require_uuid(self.operation_id, field_name="operation_id")
        _require_uuid(self.correlation_id, field_name="correlation_id")
        if self.causation_id is None:
            if self.operation_id != self.correlation_id:
                raise ValueError(
                    "a root journal entry must use operation_id as correlation_id"
                )
        else:
            _require_uuid(self.causation_id, field_name="causation_id")
            if self.operation_id in {self.correlation_id, self.causation_id}:
                raise ValueError("child journal trace identifiers must be distinct")
        if self.actor_id is not None and (
            isinstance(self.actor_id, bool) or self.actor_id <= 0
        ):
            raise ValueError("actor_id must be a positive integer")
        if self.initiated_by not in _INITIATORS:
            raise ValueError("journal initiator is invalid")
        if self.origin_kind not in _ORIGIN_KINDS:
            raise ValueError("journal origin kind is invalid")
        _validate_origin_projection(self)
        if (
            self.credential_kind is not None
            and self.credential_kind not in _CREDENTIAL_KINDS
        ):
            raise ValueError("journal credential kind is invalid")
        _validate_credential_projection(self)
        for field_name in ("request_id", "conversation_id", "turn_id", "job_id"):
            value = getattr(self, field_name)
            if value is not None:
                _require_uuid(value, field_name=field_name)
        if not isinstance(self.action, OperationAction):
            raise TypeError("journal entry action must be an OperationAction")
        object.__setattr__(self, "resources", _normalize_resources(self.resources))
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("journal timestamps must be timezone-aware")
        if self.created_at != self.updated_at:
            raise ValueError("append-only journal timestamps must be identical")


def _normalize_resources(
    resources: tuple[ResourceRef, ...],
) -> tuple[ResourceRef, ...]:
    normalized = tuple(sorted(set(resources)))
    if not normalized:
        raise ValueError("an operation change requires at least one resource")
    if len(normalized) > MAX_RESOURCE_REFS:
        raise ValueError(
            f"an operation change supports at most {MAX_RESOURCE_REFS} resources"
        )
    return normalized


def _require_uuid(value: UUID, *, field_name: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{field_name} must be a non-zero UUID")


def _validate_optional_safe_projection(
    value: str | None,
    *,
    field_name: str,
) -> None:
    if value is not None and (
        not isinstance(value, str) or _SAFE_PROJECTION_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{field_name} must be a bounded safe reference")


def _validate_optional_digest(value: str | None, *, field_name: str) -> None:
    if value is not None and (
        not isinstance(value, str) or _DIGEST_REFERENCE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{field_name} must be a canonical SHA-256 reference")


def _validate_origin_projection(entry: OperationJournalEntry) -> None:
    if entry.origin_kind in {"http", "conversation"}:
        if entry.origin_name is not None or entry.origin_reference is not None:
            raise ValueError(f"{entry.origin_kind} journal projection is invalid")
        if entry.request_id is None or entry.job_id is not None:
            raise ValueError(f"{entry.origin_kind} journal identifiers are invalid")
        if entry.origin_kind == "http" and (
            entry.conversation_id is not None or entry.turn_id is not None
        ):
            raise ValueError("HTTP journal identifiers are invalid")
        if entry.origin_kind == "conversation" and (
            entry.conversation_id is None or entry.turn_id is None
        ):
            raise ValueError("conversation journal identifiers are incomplete")
        return
    if entry.origin_kind == "mcp":
        _validate_optional_safe_projection(
            entry.origin_name,
            field_name="origin_name",
        )
        if entry.origin_name is None:
            raise ValueError("mcp origin_name is required")
        _validate_optional_digest(
            entry.origin_reference,
            field_name="origin_reference",
        )
        if entry.origin_reference is None:
            raise ValueError("mcp origin_reference is required")
        if (
            entry.request_id is None
            or entry.conversation_id is not None
            or entry.turn_id is not None
            or entry.job_id is not None
        ):
            raise ValueError("MCP journal identifiers are invalid")
        return
    if entry.origin_kind == "job":
        if entry.origin_name != "job":
            raise ValueError("job origin_name must be 'job'")
        _validate_optional_digest(
            entry.origin_reference,
            field_name="origin_reference",
        )
        if (
            entry.job_id is None
            or entry.conversation_id is not None
            or entry.turn_id is not None
        ):
            raise ValueError("job journal identifiers are invalid")
        return
    if entry.origin_kind == "webhook":
        _validate_optional_safe_projection(
            entry.origin_name,
            field_name="origin_name",
        )
        if entry.origin_name is None:
            raise ValueError("webhook origin_name is required")
        _validate_optional_digest(
            entry.origin_reference,
            field_name="origin_reference",
        )
        if (
            entry.request_id is None
            or entry.conversation_id is not None
            or entry.turn_id is not None
            or entry.job_id is not None
        ):
            raise ValueError("webhook journal identifiers are invalid")
        return
    if entry.origin_kind == "oauth_callback":
        _validate_optional_safe_projection(
            entry.origin_name,
            field_name="origin_name",
        )
        if entry.origin_name is None or entry.origin_reference is not None:
            raise ValueError("OAuth callback journal projection is invalid")
        if (
            entry.request_id is None
            or entry.conversation_id is not None
            or entry.turn_id is not None
            or entry.job_id is not None
        ):
            raise ValueError("OAuth callback journal identifiers are invalid")
        return
    if entry.origin_kind == "scheduler":
        _validate_optional_safe_projection(
            entry.origin_name,
            field_name="origin_name",
        )
        if entry.origin_name is None or entry.origin_reference is None:
            raise ValueError("scheduler journal projection is incomplete")
        try:
            run_id = UUID(entry.origin_reference)
        except (AttributeError, ValueError) as error:
            raise ValueError("scheduler origin_reference must be a UUID") from error
        if str(run_id) != entry.origin_reference or run_id.int == 0:
            raise ValueError("scheduler origin_reference must be a canonical UUID")
        if any(
            value is not None
            for value in (
                entry.request_id,
                entry.conversation_id,
                entry.turn_id,
                entry.job_id,
            )
        ):
            raise ValueError("scheduler journal identifiers are invalid")


def _validate_credential_projection(entry: OperationJournalEntry) -> None:
    if entry.credential_kind is None:
        if entry.credential_id is not None:
            raise ValueError("credential_id requires a credential_kind")
        return
    if entry.credential_kind == "cloud_session":
        if entry.credential_id is not None:
            raise ValueError("cloud sessions cannot persist an identifier")
        return
    if entry.credential_kind == "access_key":
        if entry.credential_id is None:
            raise ValueError("access key credential_id is required")
        try:
            access_key_id = UUID(entry.credential_id)
        except (AttributeError, ValueError) as error:
            raise ValueError("access key credential_id must be a UUID") from error
        if str(access_key_id) != entry.credential_id or access_key_id.int == 0:
            raise ValueError("access key credential_id must be a canonical UUID")
        return
    _validate_optional_safe_projection(
        entry.credential_id,
        field_name="credential_id",
    )


__all__ = [
    "MAX_RESOURCE_REFS",
    "OperationAction",
    "OperationChange",
    "OperationJournalEntry",
    "ResourceRef",
]
