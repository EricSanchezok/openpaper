"""Transport-neutral authorization for one document inside a paper collection."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.search import PaperCollection
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


class PaperCollectionAccessPort(Protocol):
    def contains(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
        document_id: UUID,
    ) -> bool: ...


class RequirePaperInCollection:
    def __init__(self, access: PaperCollectionAccessPort) -> None:
        self._access = access

    def __call__(
        self,
        *,
        actor: Actor,
        collection: PaperCollection,
        document_id: UUID,
        anchor_document_id: UUID | None,
    ) -> None:
        if document_id == anchor_document_id:
            return
        if not self._access.contains(
            actor=actor,
            collection=collection,
            document_id=document_id,
        ):
            raise AppError(
                code="tool_document_outside_context",
                message="This paper is not in the active conversation context",
                kind=FailureKind.NOT_FOUND,
            )
