"""Cross-module OAuth, SQLAlchemy, and telemetry adapter for Zotero."""

from __future__ import annotations

from datetime import UTC, datetime

from app.database.telemetry import track_event
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroImportStatusItem,
    ZoteroImportStatusListResponse,
    ZoteroLibraryItem,
    ZoteroLibraryResponse,
    ZoteroStatusResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.infrastructure.connection_repository import (
    zotero_connection_repository,
)
from app.modules.integrations.zotero.infrastructure.import_repository import (
    zotero_import_repository,
)
from app.modules.integrations.zotero.infrastructure.oauth import zotero_auth_client
from app.bootstrap.adapters.zotero_workflow import (
    import_batch,
    list_library,
    sync_batch,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


class DefaultZoteroGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def begin_oauth(self, *, user_id: int) -> str | None:
        request_token = zotero_auth_client.get_request_token()
        if request_token is None:
            return None
        zotero_connection_repository.delete_pending_for_user(
            db=self._db,
            user_id=user_id,
        )
        zotero_connection_repository.create_pending(
            db=self._db,
            user_id=user_id,
            oauth_token=request_token.oauth_token,
            oauth_token_secret=request_token.oauth_token_secret,
        )
        return zotero_auth_client.get_authorize_url(request_token.oauth_token)

    def complete_oauth(self, *, oauth_token: str, oauth_verifier: str) -> bool:
        pending = zotero_connection_repository.get_pending_by_token(
            db=self._db,
            oauth_token=oauth_token,
        )
        if pending is None or pending.user_id is None:
            return False
        expires_at = pending.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < datetime.now(UTC):
            zotero_connection_repository.delete_pending(
                db=self._db,
                pending=pending,
            )
            return False
        access_token = zotero_auth_client.get_access_token(
            request_token=oauth_token,
            request_token_secret=pending.oauth_token_secret,
            verifier=oauth_verifier,
        )
        if access_token is None:
            return False
        zotero_connection_repository.upsert_connection(
            db=self._db,
            user_id=pending.user_id,
            zotero_user_id=access_token.zotero_user_id,
            api_key=access_token.api_key,
        )
        zotero_connection_repository.delete_pending(db=self._db, pending=pending)
        track_event(
            "zotero_connected",
            user_id=str(pending.user_id),
            db=self._db,
        )
        return True

    def status(self, *, user_id: int) -> ZoteroStatusResponse:
        connection = zotero_connection_repository.get_by_user_id(
            db=self._db,
            user_id=user_id,
        )
        if connection is None:
            return ZoteroStatusResponse(connected=False)
        return ZoteroStatusResponse(
            connected=True,
            connected_at=connection.created_at,
            last_synced_at=zotero_import_repository.get_max_last_synced_at(
                self._db,
                user_id=user_id,
            ),
        )

    def disconnect(self, *, user_id: int) -> bool:
        return zotero_connection_repository.delete_by_user_id(
            db=self._db,
            user_id=user_id,
        )

    def connected(self, *, user_id: int) -> bool:
        return (
            zotero_connection_repository.get_by_user_id(
                self._db,
                user_id=user_id,
            )
            is not None
        )

    def library(self, *, actor: Actor) -> ZoteroLibraryResponse:
        result = list_library(self._db, user=actor)
        return ZoteroLibraryResponse(
            items=[ZoteroLibraryItem(**item) for item in result["items"]],
            remaining_slots=result["remaining_slots"],
        )

    async def import_items(
        self,
        *,
        actor: Actor,
        request: ZoteroImportRequest,
    ) -> ZoteroImportResponse:
        result = await import_batch(
            self._db,
            user=actor,
            item_keys=request.item_keys,
        )
        return ZoteroImportResponse(
            imported=[ZoteroImportItemResult(**item) for item in result["imported"]],
            imported_count=result["imported_count"],
            imported_via_url=result["imported_via_url"],
            skipped_already_imported=result["skipped_already_imported"],
            errors=[ZoteroImportError(**error) for error in result["errors"]],
        )

    async def sync(self, *, actor: Actor) -> ZoteroSyncResponse:
        result = await sync_batch(self._db, user=actor, limit=50)
        return ZoteroSyncResponse(
            synced_papers_count=result["synced_papers_count"],
            new_annotations_count=result["new_annotations_count"],
        )

    def imports(
        self,
        *,
        user_id: int,
        item_keys: list[str] | None,
    ) -> ZoteroImportStatusListResponse:
        rows = (
            zotero_import_repository.list_by_item_keys(
                self._db,
                user_id=user_id,
                item_keys=item_keys,
            )
            if item_keys
            else zotero_import_repository.list_recent_by_user(
                self._db,
                user_id=user_id,
            )
        )
        return ZoteroImportStatusListResponse(
            items=[
                ZoteroImportStatusItem(
                    zotero_item_key=row.zotero_item_key,
                    document_id=str(row.document_id) if row.document_id else None,
                    upload_job_id=(
                        str(row.upload_job_id) if row.upload_job_id else None
                    ),
                    import_source=row.import_source,
                    status=row.status,
                    title=title,
                    error_message=row.error_message,
                    created_at=row.created_at,
                    last_synced_at=row.last_synced_at,
                )
                for row, title in rows
            ]
        )


class PostHogZoteroEvents:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object],
    ) -> None:
        track_event(
            name,
            user_id=str(actor.id),
            properties=properties,
            db=self._db,
        )
