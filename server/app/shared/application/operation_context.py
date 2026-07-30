"""Immutable provenance for an authenticated application operation."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

_DIGEST_REFERENCE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NAMED_ORIGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CREDENTIAL_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}$")


def _require_uuid(value: UUID, *, field_name: str) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{field_name} must be a non-zero UUID")


def _require_digest_reference(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or _DIGEST_REFERENCE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical SHA-256 reference")


def _require_named_origin(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or _NAMED_ORIGIN_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be 1-128 lowercase letters, digits, '.', '_' or '-'"
        )


@dataclass(frozen=True, slots=True)
class OperationTrace:
    operation_id: UUID
    correlation_id: UUID
    causation_id: UUID | None

    def __post_init__(self) -> None:
        _require_uuid(self.operation_id, field_name="operation_id")
        _require_uuid(self.correlation_id, field_name="correlation_id")
        if self.causation_id is None:
            if self.correlation_id != self.operation_id:
                raise ValueError(
                    "a root trace must use its operation_id as correlation_id"
                )
            return
        _require_uuid(self.causation_id, field_name="causation_id")
        if self.operation_id in {self.correlation_id, self.causation_id}:
            raise ValueError(
                "a child operation_id must differ from correlation_id and causation_id"
            )


class OperationInitiator(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class RequestReference:
    request_id: UUID

    def __post_init__(self) -> None:
        _require_uuid(self.request_id, field_name="request_id")


@dataclass(frozen=True, slots=True)
class HttpOrigin:
    request: RequestReference
    kind: Literal["http"] = field(init=False, default="http")


@dataclass(frozen=True, slots=True)
class ConversationOrigin:
    request: RequestReference
    conversation_id: UUID
    turn_id: UUID
    kind: Literal["conversation"] = field(init=False, default="conversation")

    def __post_init__(self) -> None:
        _require_uuid(self.conversation_id, field_name="conversation_id")
        _require_uuid(self.turn_id, field_name="turn_id")


@dataclass(frozen=True, slots=True)
class McpOrigin:
    request: RequestReference
    mcp_session_ref: str | None
    mcp_request_ref: str
    kind: Literal["mcp"] = field(init=False, default="mcp")

    def __post_init__(self) -> None:
        if self.mcp_session_ref is not None:
            _require_digest_reference(
                self.mcp_session_ref,
                field_name="mcp_session_ref",
            )
        _require_digest_reference(
            self.mcp_request_ref,
            field_name="mcp_request_ref",
        )


@dataclass(frozen=True, slots=True)
class JobOrigin:
    job_id: UUID
    delivery_ref: str | None
    request_id: UUID | None
    kind: Literal["job"] = field(init=False, default="job")

    def __post_init__(self) -> None:
        _require_uuid(self.job_id, field_name="job_id")
        if self.delivery_ref is not None:
            _require_digest_reference(self.delivery_ref, field_name="delivery_ref")
        if self.request_id is not None:
            _require_uuid(self.request_id, field_name="request_id")


@dataclass(frozen=True, slots=True)
class WebhookOrigin:
    request: RequestReference
    provider: str
    provider_event_ref: str | None
    kind: Literal["webhook"] = field(init=False, default="webhook")

    def __post_init__(self) -> None:
        _require_named_origin(self.provider, field_name="provider")
        if self.provider_event_ref is not None:
            _require_digest_reference(
                self.provider_event_ref,
                field_name="provider_event_ref",
            )


@dataclass(frozen=True, slots=True)
class OAuthCallbackOrigin:
    request: RequestReference
    provider: str
    kind: Literal["oauth_callback"] = field(
        init=False,
        default="oauth_callback",
    )

    def __post_init__(self) -> None:
        _require_named_origin(self.provider, field_name="provider")


@dataclass(frozen=True, slots=True)
class SchedulerOrigin:
    task_name: str
    run_id: UUID
    kind: Literal["scheduler"] = field(init=False, default="scheduler")

    def __post_init__(self) -> None:
        _require_named_origin(self.task_name, field_name="task_name")
        _require_uuid(self.run_id, field_name="run_id")


type OperationOrigin = (
    HttpOrigin
    | ConversationOrigin
    | McpOrigin
    | JobOrigin
    | WebhookOrigin
    | OAuthCallbackOrigin
    | SchedulerOrigin
)


class CredentialKind(StrEnum):
    CLOUD_SESSION = "cloud_session"
    ACCESS_KEY = "access_key"
    INTERNAL_SIGNATURE = "internal_signature"
    PROVIDER_SIGNATURE = "provider_signature"


@dataclass(frozen=True, slots=True)
class CredentialRef:
    kind: CredentialKind
    credential_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CredentialKind):
            raise ValueError("credential kind is invalid")
        if self.kind is CredentialKind.CLOUD_SESSION:
            if self.credential_id is not None:
                raise ValueError(
                    "cloud session credentials cannot persist an identifier"
                )
            return
        if self.kind is CredentialKind.ACCESS_KEY:
            if self.credential_id is None:
                raise ValueError("access key credentials require an identifier")
            try:
                access_key_id = UUID(self.credential_id)
            except (AttributeError, ValueError) as error:
                raise ValueError(
                    "access key credential_id must be a canonical UUID"
                ) from error
            if str(access_key_id) != self.credential_id or access_key_id.int == 0:
                raise ValueError("access key credential_id must be a canonical UUID")
            return
        if self.credential_id is not None and (
            _CREDENTIAL_REFERENCE_PATTERN.fullmatch(self.credential_id) is None
        ):
            raise ValueError("credential_id must be a bounded non-sensitive reference")


@dataclass(frozen=True, slots=True)
class OperationContext:
    trace: OperationTrace
    initiated_by: OperationInitiator
    origin: OperationOrigin
    credential: CredentialRef | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.initiated_by, OperationInitiator):
            raise ValueError("operation initiator is invalid")
        if not isinstance(
            self.origin,
            (
                HttpOrigin,
                ConversationOrigin,
                McpOrigin,
                JobOrigin,
                WebhookOrigin,
                OAuthCallbackOrigin,
                SchedulerOrigin,
            ),
        ):
            raise ValueError("operation origin is invalid")
        _validate_credential(self.origin, self.credential)
        _validate_initiator(
            self.origin,
            self.initiated_by,
            is_root=self.trace.causation_id is None,
        )


class OperationContextFactory:
    """Construct structurally valid provenance without authenticating a caller."""

    def __init__(self, generate_uuid: Callable[[], UUID] = uuid4) -> None:
        self._generate_uuid = generate_uuid

    def root(
        self,
        *,
        initiated_by: OperationInitiator,
        origin: OperationOrigin,
        credential: CredentialRef | None,
    ) -> OperationContext:
        operation_id = self._next_uuid()
        return OperationContext(
            trace=OperationTrace(
                operation_id=operation_id,
                correlation_id=operation_id,
                causation_id=None,
            ),
            initiated_by=initiated_by,
            origin=origin,
            credential=credential,
        )

    def child(
        self,
        parent: OperationContext,
        *,
        initiated_by: OperationInitiator,
        origin: OperationOrigin | None = None,
    ) -> OperationContext:
        child_origin = parent.origin if origin is None else origin
        if child_origin != parent.origin:
            raise ValueError(
                "a child must retain its parent origin; use resume for a new origin"
            )
        operation_id = self._next_uuid()
        return OperationContext(
            trace=OperationTrace(
                operation_id=operation_id,
                correlation_id=parent.trace.correlation_id,
                causation_id=parent.trace.operation_id,
            ),
            initiated_by=initiated_by,
            origin=child_origin,
            credential=parent.credential,
        )

    def resume(
        self,
        *,
        correlation_id: UUID,
        causation_id: UUID,
        initiated_by: OperationInitiator,
        origin: OperationOrigin,
        credential: CredentialRef | None,
    ) -> OperationContext:
        _require_uuid(correlation_id, field_name="correlation_id")
        _require_uuid(causation_id, field_name="causation_id")
        operation_id = self._next_uuid()
        return OperationContext(
            trace=OperationTrace(
                operation_id=operation_id,
                correlation_id=correlation_id,
                causation_id=causation_id,
            ),
            initiated_by=initiated_by,
            origin=origin,
            credential=credential,
        )

    def _next_uuid(self) -> UUID:
        value = self._generate_uuid()
        _require_uuid(value, field_name="generated operation_id")
        return value


def _validate_credential(
    origin: OperationOrigin,
    credential: CredentialRef | None,
) -> None:
    expected: CredentialKind | None
    allows_none = False
    if isinstance(origin, (HttpOrigin, ConversationOrigin)):
        expected = CredentialKind.CLOUD_SESSION
    elif isinstance(origin, McpOrigin):
        expected = CredentialKind.ACCESS_KEY
    elif isinstance(origin, JobOrigin):
        expected = CredentialKind.INTERNAL_SIGNATURE
        allows_none = True
    elif isinstance(origin, WebhookOrigin):
        expected = CredentialKind.PROVIDER_SIGNATURE
    else:
        expected = None
        allows_none = True

    if credential is None:
        if allows_none:
            return
        raise ValueError(
            f"{origin.kind} operations require an authenticated credential"
        )
    if expected is None or credential.kind is not expected:
        raise ValueError(f"{credential.kind.value} is invalid for {origin.kind} origin")


def _validate_initiator(
    origin: OperationOrigin,
    initiated_by: OperationInitiator,
    *,
    is_root: bool,
) -> None:
    if isinstance(origin, HttpOrigin):
        allowed = (
            {OperationInitiator.USER}
            if is_root
            else {OperationInitiator.AGENT, OperationInitiator.SYSTEM}
        )
    elif isinstance(origin, ConversationOrigin):
        allowed = (
            {OperationInitiator.USER}
            if is_root
            else {OperationInitiator.AGENT, OperationInitiator.SYSTEM}
        )
    elif isinstance(origin, McpOrigin):
        allowed = (
            {OperationInitiator.AGENT}
            if is_root
            else {OperationInitiator.AGENT, OperationInitiator.SYSTEM}
        )
    else:
        allowed = {OperationInitiator.SYSTEM}
    if initiated_by not in allowed:
        stage = "root" if is_root else "child/resumed"
        raise ValueError(
            f"{initiated_by.value} is invalid for a {stage} {origin.kind} operation"
        )


__all__ = [
    "ConversationOrigin",
    "CredentialKind",
    "CredentialRef",
    "HttpOrigin",
    "JobOrigin",
    "McpOrigin",
    "OAuthCallbackOrigin",
    "OperationContext",
    "OperationContextFactory",
    "OperationInitiator",
    "OperationOrigin",
    "OperationTrace",
    "RequestReference",
    "SchedulerOrigin",
    "WebhookOrigin",
]
