"""Personal Library and public-share use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.documents import (
    CollectPublicPaperResponse,
    DocumentResponse,
    LibraryPaperListResponse,
    LibraryPaperResponse,
    LibraryPaperShareResponse,
    LibraryPaperUpdateRequest,
    PublicPaperOwnerResponse,
    PublicPaperResponse,
)
from app.modules.papers.application.downloads import PaperDownloadSigner
from app.modules.papers.application.actions import (
    LIBRARY_PAPER_COLLECTED,
    LIBRARY_PAPER_REMOVED,
    LIBRARY_PAPER_SHARED,
    LIBRARY_PAPER_UNSHARED,
    LIBRARY_PAPER_UPDATED,
)
from app.modules.jobs.application.actions import JOB_CREATED
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationChange,
    ResourceRef,
)
from app.shared.application import Actor
from app.shared.application.operation_context import OperationContext
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class PublicShare:
    document_id: UUID
    storage_key: str
    document: DocumentResponse
    owner: PublicPaperOwnerResponse


@dataclass(frozen=True, slots=True)
class LibraryPaperUpdateResult:
    response: LibraryPaperResponse
    changed: bool


@dataclass(frozen=True, slots=True)
class LibraryPaperAttachment:
    library_entry_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class LibraryPaperRemoval:
    created_gc_job_id: UUID | None


class PaperLibraryGateway(Protocol):
    def list(self, *, user_id: int) -> list[LibraryPaperResponse]: ...

    def get(self, *, user_id: int, document_id: UUID) -> LibraryPaperResponse: ...

    def update(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperUpdateResult: ...

    def share(self, *, user_id: int, document_id: UUID) -> str: ...

    def unshare(self, *, user_id: int, document_id: UUID) -> bool: ...

    def remove(
        self,
        *,
        user_id: int,
        document_id: UUID,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> LibraryPaperRemoval: ...

    def public_share(self, *, share_token: str) -> PublicShare: ...

    def find_entry_id(self, *, user_id: int, document_id: UUID) -> UUID | None: ...

    def attach(
        self,
        *,
        user_id: int,
        document_id: UUID,
    ) -> LibraryPaperAttachment: ...


class LibraryCapacity(Protocol):
    def require(self, *, actor: Actor, document_id: UUID) -> None: ...


class PaperLibrary:
    def __init__(
        self,
        *,
        gateway: PaperLibraryGateway,
        capacity: LibraryCapacity,
        signer: PaperDownloadSigner,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._signer = signer
        self._journal = journal

    def list(self, *, actor: Actor) -> LibraryPaperListResponse:
        return LibraryPaperListResponse(items=self._gateway.list(user_id=actor.id))

    def get(self, *, actor: Actor, document_id: UUID) -> LibraryPaperResponse:
        return self._gateway.get(user_id=actor.id, document_id=document_id)

    def update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperResponse:
        result = self._gateway.update(
            user_id=actor.id,
            document_id=document_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_PAPER_UPDATED,
                resources=(
                    ResourceRef(type="document", id=str(document_id)),
                    ResourceRef(
                        type="library_paper",
                        id=str(result.response.library_entry_id),
                    ),
                ),
            )
        return result.response

    def share(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> LibraryPaperShareResponse:
        share_token = self._gateway.share(
            user_id=actor.id,
            document_id=document_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=LIBRARY_PAPER_SHARED,
            resources=(ResourceRef(type="document", id=str(document_id)),),
        )
        return LibraryPaperShareResponse(
            share_token=share_token,
            is_public=True,
        )

    def unshare(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> None:
        changed = self._gateway.unshare(
            user_id=actor.id,
            document_id=document_id,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_PAPER_UNSHARED,
                resources=(ResourceRef(type="document", id=str(document_id)),),
            )

    def remove(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> None:
        result = self._gateway.remove(
            user_id=actor.id,
            document_id=document_id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        changes = [
            OperationChange(
                action=LIBRARY_PAPER_REMOVED,
                resources=(ResourceRef(type="document", id=str(document_id)),),
            )
        ]
        if result.created_gc_job_id is not None:
            changes.append(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(
                        ResourceRef(type="job", id=str(result.created_gc_job_id)),
                    ),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )

    def get_public(self, *, share_token: str) -> PublicPaperResponse:
        shared = self._gateway.public_share(share_token=share_token)
        try:
            file_url = self._signer.sign(storage_key=shared.storage_key)
        except RuntimeError as exc:
            raise AppError(
                code="document_file_url_unavailable",
                message="The document file is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        return PublicPaperResponse(
            document=shared.document,
            file_url=file_url,
            owner=shared.owner,
        )

    def collect_public(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        share_token: str,
    ) -> CollectPublicPaperResponse:
        shared = self._gateway.public_share(share_token=share_token)
        existing_id = self._gateway.find_entry_id(
            user_id=actor.id,
            document_id=shared.document_id,
        )
        if existing_id is not None:
            return CollectPublicPaperResponse(
                document_id=shared.document_id,
                library_entry_id=existing_id,
                already_exists=True,
            )
        self._capacity.require(actor=actor, document_id=shared.document_id)
        attached = self._gateway.attach(
            user_id=actor.id,
            document_id=shared.document_id,
        )
        if attached.created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=LIBRARY_PAPER_COLLECTED,
                resources=(
                    ResourceRef(type="document", id=str(shared.document_id)),
                    ResourceRef(
                        type="library_paper",
                        id=str(attached.library_entry_id),
                    ),
                ),
            )
        return CollectPublicPaperResponse(
            document_id=shared.document_id,
            library_entry_id=attached.library_entry_id,
            already_exists=not attached.created,
        )
