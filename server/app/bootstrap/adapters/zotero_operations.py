"""Owned short-transaction runner for Zotero remote workflows."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.adapters.zotero_workflow import import_batch, sync_batch
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroImport,
    ZoteroCredentials,
)
from app.shared.application import Actor


class DefaultZoteroOperations:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

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
