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
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class PublicShare:
    document_id: UUID
    storage_key: str
    document: DocumentResponse
    owner: PublicPaperOwnerResponse


class PaperLibraryGateway(Protocol):
    def list(self, *, user_id: int) -> list[LibraryPaperResponse]: ...

    def get(self, *, user_id: int, document_id: UUID) -> LibraryPaperResponse: ...

    def update(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperResponse: ...

    def share(self, *, user_id: int, document_id: UUID) -> str: ...

    def unshare(self, *, user_id: int, document_id: UUID) -> None: ...

    def remove(self, *, user_id: int, document_id: UUID) -> None: ...

    def public_share(self, *, share_token: str) -> PublicShare: ...

    def find_entry_id(self, *, user_id: int, document_id: UUID) -> UUID | None: ...

    def attach(self, *, user_id: int, document_id: UUID) -> UUID: ...


class LibraryCapacity(Protocol):
    def require(self, *, actor: Actor, document_id: UUID) -> None: ...


class PaperLibrary:
    def __init__(
        self,
        *,
        gateway: PaperLibraryGateway,
        capacity: LibraryCapacity,
        signer: PaperDownloadSigner,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._signer = signer

    def list(self, *, actor: Actor) -> LibraryPaperListResponse:
        return LibraryPaperListResponse(items=self._gateway.list(user_id=actor.id))

    def get(self, *, actor: Actor, document_id: UUID) -> LibraryPaperResponse:
        return self._gateway.get(user_id=actor.id, document_id=document_id)

    def update(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        request: LibraryPaperUpdateRequest,
    ) -> LibraryPaperResponse:
        return self._gateway.update(
            user_id=actor.id,
            document_id=document_id,
            request=request,
        )

    def share(
        self,
        *,
        actor: Actor,
        document_id: UUID,
    ) -> LibraryPaperShareResponse:
        return LibraryPaperShareResponse(
            share_token=self._gateway.share(
                user_id=actor.id,
                document_id=document_id,
            ),
            is_public=True,
        )

    def unshare(self, *, actor: Actor, document_id: UUID) -> None:
        self._gateway.unshare(user_id=actor.id, document_id=document_id)

    def remove(self, *, actor: Actor, document_id: UUID) -> None:
        self._gateway.remove(user_id=actor.id, document_id=document_id)

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
        entry_id = self._gateway.attach(
            user_id=actor.id,
            document_id=shared.document_id,
        )
        return CollectPublicPaperResponse(
            document_id=shared.document_id,
            library_entry_id=entry_id,
            already_exists=False,
        )
