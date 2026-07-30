"""Library-tag use cases shared by every transport."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagAssignmentResponse,
    LibraryTagCreateRequest,
    LibraryTagListResponse,
    LibraryTagResponse,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor
from app.shared.application.operation_context import OperationContext


LIBRARY_TAG_CREATED = OperationAction("library.tag_created")
LIBRARY_TAGS_ASSIGNED = OperationAction("library.tags_assigned")
LIBRARY_TAG_UNASSIGNED = OperationAction("library.tag_unassigned")


class LibraryTagGateway(Protocol):
    def list(self, *, user_id: int) -> list[LibraryTagResponse]: ...

    def create(
        self,
        *,
        user_id: int,
        request: LibraryTagCreateRequest,
    ) -> LibraryTagResponse: ...

    def assign(
        self,
        *,
        user_id: int,
        request: LibraryTagAssignmentRequest,
    ) -> int: ...

    def remove(
        self,
        *,
        user_id: int,
        document_id: UUID,
        tag_id: UUID,
    ) -> None: ...


class LibraryTags:
    def __init__(
        self,
        gateway: LibraryTagGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def list(self, *, actor: Actor) -> LibraryTagListResponse:
        return LibraryTagListResponse(items=self._gateway.list(user_id=actor.id))

    def create(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: LibraryTagCreateRequest,
    ) -> LibraryTagResponse:
        result = self._gateway.create(user_id=actor.id, request=request)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_TAG_CREATED,
            resources=(ResourceRef(type="library_tag", id=str(result.id)),),
        )
        return result

    def assign(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: LibraryTagAssignmentRequest,
    ) -> LibraryTagAssignmentResponse:
        assigned_count = self._gateway.assign(
            user_id=actor.id,
            request=request,
        )
        if assigned_count:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_TAGS_ASSIGNED,
                resources=(ResourceRef(type="library", id=str(actor.id)),),
            )
        return LibraryTagAssignmentResponse(assigned_count=assigned_count)

    def remove(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        tag_id: UUID,
    ) -> None:
        self._gateway.remove(
            user_id=actor.id,
            document_id=document_id,
            tag_id=tag_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_TAG_UNASSIGNED,
            resources=(
                ResourceRef(type="document", id=str(document_id)),
                ResourceRef(type="library_tag", id=str(tag_id)),
            ),
        )
