"""Project successful business changes into durable operation attribution."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.modules.operation_journal.application.ports import OperationJournalStore
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    OperationJournalEntry,
    ResourceRef,
)
from app.shared.application.actor import Actor
from app.shared.application.clock import Clock
from app.shared.application.operation_context import (
    ConversationOrigin,
    HttpOrigin,
    JobOrigin,
    McpOrigin,
    OAuthCallbackOrigin,
    OperationContext,
    SchedulerOrigin,
    WebhookOrigin,
)


@dataclass(frozen=True, slots=True)
class _OriginProjection:
    origin_name: str | None
    origin_reference: str | None
    request_id: UUID | None
    conversation_id: UUID | None
    turn_id: UUID | None
    job_id: UUID | None


class OperationJournal:
    """Append-only application sink bound to the current UnitOfWork session."""

    def __init__(
        self,
        *,
        store: OperationJournalStore,
        clock: Clock,
        generate_uuid: Callable[[], UUID] = uuid4,
    ) -> None:
        self._store = store
        self._clock = clock
        self._generate_uuid = generate_uuid

    def append(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        action: OperationAction,
        resources: Iterable[ResourceRef],
    ) -> OperationJournalEntry:
        entries = self.append_many(
            actor=actor,
            operation=operation,
            changes=(
                OperationChange(
                    action=action,
                    resources=tuple(resources),
                ),
            ),
        )
        return entries[0]

    def append_many(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        changes: Iterable[OperationChange],
    ) -> tuple[OperationJournalEntry, ...]:
        normalized_changes = tuple(changes)
        if not normalized_changes:
            return ()
        projection = _project_origin(operation)
        now = self._clock.now()
        entries = tuple(
            OperationJournalEntry(
                entry_id=self._generate_uuid(),
                operation_id=operation.trace.operation_id,
                correlation_id=operation.trace.correlation_id,
                causation_id=operation.trace.causation_id,
                actor_id=actor.id if actor is not None else None,
                initiated_by=operation.initiated_by.value,
                origin_kind=operation.origin.kind,
                origin_name=projection.origin_name,
                origin_reference=projection.origin_reference,
                credential_kind=(
                    operation.credential.kind.value
                    if operation.credential is not None
                    else None
                ),
                credential_id=(
                    operation.credential.credential_id
                    if operation.credential is not None
                    else None
                ),
                request_id=projection.request_id,
                conversation_id=projection.conversation_id,
                turn_id=projection.turn_id,
                job_id=projection.job_id,
                action=change.action,
                resources=change.resources,
                created_at=now,
                updated_at=now,
            )
            for change in normalized_changes
        )
        self._store.append(entries)
        return entries


def _project_origin(operation: OperationContext) -> _OriginProjection:
    origin = operation.origin
    if isinstance(origin, HttpOrigin):
        return _OriginProjection(
            origin_name=None,
            origin_reference=None,
            request_id=origin.request.request_id,
            conversation_id=None,
            turn_id=None,
            job_id=None,
        )
    if isinstance(origin, ConversationOrigin):
        return _OriginProjection(
            origin_name=None,
            origin_reference=None,
            request_id=origin.request.request_id,
            conversation_id=origin.conversation_id,
            turn_id=origin.turn_id,
            job_id=None,
        )
    if isinstance(origin, McpOrigin):
        return _OriginProjection(
            origin_name=origin.mcp_session_ref or "stateless",
            origin_reference=origin.mcp_request_ref,
            request_id=origin.request.request_id,
            conversation_id=None,
            turn_id=None,
            job_id=None,
        )
    if isinstance(origin, JobOrigin):
        return _OriginProjection(
            origin_name="job",
            origin_reference=origin.delivery_ref,
            request_id=origin.request_id,
            conversation_id=None,
            turn_id=None,
            job_id=origin.job_id,
        )
    if isinstance(origin, WebhookOrigin):
        return _OriginProjection(
            origin_name=origin.provider,
            origin_reference=origin.provider_event_ref,
            request_id=origin.request.request_id,
            conversation_id=None,
            turn_id=None,
            job_id=None,
        )
    if isinstance(origin, OAuthCallbackOrigin):
        return _OriginProjection(
            origin_name=origin.provider,
            origin_reference=None,
            request_id=origin.request.request_id,
            conversation_id=None,
            turn_id=None,
            job_id=None,
        )
    if isinstance(origin, SchedulerOrigin):
        return _OriginProjection(
            origin_name=origin.task_name,
            origin_reference=str(origin.run_id),
            request_id=None,
            conversation_id=None,
            turn_id=None,
            job_id=None,
        )
    raise TypeError(f"unsupported operation origin: {type(origin).__name__}")


__all__ = ["OperationJournal"]
