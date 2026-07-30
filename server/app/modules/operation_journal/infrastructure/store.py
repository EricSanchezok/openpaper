"""Session-bound append-only operation journal store."""

from __future__ import annotations

from app.modules.operation_journal.application import OperationJournalStore
from app.modules.operation_journal.domain import OperationJournalEntry
from app.modules.operation_journal.infrastructure.models import (
    OperationJournalEntryModel,
)
from sqlalchemy.orm import Session


class SqlAlchemyOperationJournalStore(OperationJournalStore):
    def __init__(self, db: Session) -> None:
        self._db = db

    def append(self, entries: tuple[OperationJournalEntry, ...]) -> None:
        self._db.add_all(
            [
                OperationJournalEntryModel(
                    entry_id=entry.entry_id,
                    operation_id=entry.operation_id,
                    correlation_id=entry.correlation_id,
                    causation_id=entry.causation_id,
                    actor_id=entry.actor_id,
                    initiated_by=entry.initiated_by,
                    origin_kind=entry.origin_kind,
                    origin_name=entry.origin_name,
                    origin_reference=entry.origin_reference,
                    credential_kind=entry.credential_kind,
                    credential_id=entry.credential_id,
                    request_id=entry.request_id,
                    conversation_id=entry.conversation_id,
                    turn_id=entry.turn_id,
                    job_id=entry.job_id,
                    action=str(entry.action),
                    resources=[
                        {"type": resource.type, "id": resource.id}
                        for resource in entry.resources
                    ],
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                )
                for entry in entries
            ]
        )
        self._db.flush()


__all__ = ["SqlAlchemyOperationJournalStore"]
