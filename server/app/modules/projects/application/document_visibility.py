"""Public project capability for resolving document visibility."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.shared.application import Actor


class ProjectDocumentVisibilityPort(Protocol):
    def list_accessible_document_ids(
        self,
        *,
        actor: Actor,
        project_id: UUID | None = None,
    ) -> tuple[UUID, ...]: ...


class ListAccessibleProjectDocuments:
    def __init__(self, visibility: ProjectDocumentVisibilityPort) -> None:
        self._visibility = visibility

    def __call__(
        self,
        *,
        actor: Actor,
        project_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        return self._visibility.list_accessible_document_ids(
            actor=actor,
            project_id=project_id,
        )
