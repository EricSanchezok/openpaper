"""Pure classification of an authorized Document relationship."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class DocumentAccessScope(str, Enum):
    LIBRARY = "library"
    PROJECT = "project"


@dataclass(frozen=True, slots=True)
class DocumentAccessDecision:
    scope: DocumentAccessScope
    project_id: UUID | None

    @property
    def is_in_library(self) -> bool:
        return self.scope is DocumentAccessScope.LIBRARY

    @property
    def is_project_only(self) -> bool:
        return self.scope is DocumentAccessScope.PROJECT


def classify_document_access(
    *,
    has_library_entry: bool,
    accessible_project_id: UUID | None,
    project_was_requested: bool,
) -> DocumentAccessDecision | None:
    if has_library_entry and not project_was_requested:
        return DocumentAccessDecision(DocumentAccessScope.LIBRARY, None)
    if accessible_project_id is not None:
        return DocumentAccessDecision(
            DocumentAccessScope.PROJECT,
            accessible_project_id,
        )
    return None
