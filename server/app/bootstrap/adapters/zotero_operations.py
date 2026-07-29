"""Owned short-transaction runner for Zotero remote workflows."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.adapters.zotero_workflow import (
    import_batch,
    list_library,
    sync_batch,
)
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportResponse,
    ZoteroLibraryItem,
    ZoteroLibraryResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroImport,
    PreparedZoteroCallback,
    ZoteroAccessToken,
    ZoteroCredentials,
    ZoteroRequestToken,
)
from app.modules.integrations.zotero.infrastructure.oauth import zotero_auth_client
from app.shared.application import Actor


class DefaultZoteroOperations:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def request_token(self) -> ZoteroRequestToken | None:
        result = zotero_auth_client.get_request_token()
        if result is None:
            return None
        return ZoteroRequestToken(
            token=result.oauth_token,
            secret=result.oauth_token_secret,
        )

    def authorize_url(self, *, request_token: ZoteroRequestToken) -> str:
        return zotero_auth_client.get_authorize_url(request_token.token)

    def exchange_access_token(
        self,
        *,
        callback: PreparedZoteroCallback,
        verifier: str,
    ) -> ZoteroAccessToken | None:
        result = zotero_auth_client.get_access_token(
            request_token=callback.request_token.token,
            request_token_secret=callback.request_token.secret,
            verifier=verifier,
        )
        if result is None:
            return None
        return ZoteroAccessToken(
            user_id=result.zotero_user_id,
            api_key=result.api_key,
        )

    async def import_items(
        self,
        *,
        actor: Actor,
        prepared: PreparedZoteroImport,
    ) -> ZoteroImportResponse:
        with self._session_factory(expire_on_commit=False) as session:
            result = await import_batch(
                session,
                user=actor,
                item_keys=prepared.request.item_keys,
                credentials=prepared.credentials,
            )
            session.commit()
        return ZoteroImportResponse(
            imported=[ZoteroImportItemResult(**item) for item in result["imported"]],
            imported_count=result["imported_count"],
            imported_via_url=result["imported_via_url"],
            skipped_already_imported=result["skipped_already_imported"],
            errors=[ZoteroImportError(**error) for error in result["errors"]],
        )

    def library(
        self,
        *,
        actor: Actor,
        credentials: ZoteroCredentials,
    ) -> ZoteroLibraryResponse:
        with self._session_factory(expire_on_commit=False) as session:
            result = list_library(
                session,
                user=actor,
                credentials=credentials,
            )
            session.commit()
        return ZoteroLibraryResponse(
            items=[ZoteroLibraryItem(**item) for item in result["items"]],
            remaining_slots=result["remaining_slots"],
        )

    async def sync(
        self,
        *,
        actor: Actor,
        credentials: ZoteroCredentials,
    ) -> ZoteroSyncResponse:
        with self._session_factory(expire_on_commit=False) as session:
            result = await sync_batch(
                session,
                user=actor,
                credentials=credentials,
                limit=50,
            )
            session.commit()
        return ZoteroSyncResponse(
            synced_papers_count=result["synced_papers_count"],
            new_annotations_count=result["new_annotations_count"],
        )
