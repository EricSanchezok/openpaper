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
from app.shared.application import Actor


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
    def __init__(self, gateway: LibraryTagGateway) -> None:
        self._gateway = gateway

    def list(self, *, actor: Actor) -> LibraryTagListResponse:
        return LibraryTagListResponse(items=self._gateway.list(user_id=actor.id))

    def create(
        self,
        *,
        actor: Actor,
        request: LibraryTagCreateRequest,
    ) -> LibraryTagResponse:
        return self._gateway.create(user_id=actor.id, request=request)

    def assign(
        self,
        *,
        actor: Actor,
        request: LibraryTagAssignmentRequest,
    ) -> LibraryTagAssignmentResponse:
        return LibraryTagAssignmentResponse(
            assigned_count=self._gateway.assign(user_id=actor.id, request=request)
        )

    def remove(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        tag_id: UUID,
    ) -> None:
        self._gateway.remove(
            user_id=actor.id,
            document_id=document_id,
            tag_id=tag_id,
        )
