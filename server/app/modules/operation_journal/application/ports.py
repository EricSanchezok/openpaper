"""Write-only persistence port for operation attribution."""

from __future__ import annotations

from typing import Protocol

from app.modules.operation_journal.domain import OperationJournalEntry


class OperationJournalStore(Protocol):
    def append(self, entries: tuple[OperationJournalEntry, ...]) -> None: ...


__all__ = ["OperationJournalStore"]
