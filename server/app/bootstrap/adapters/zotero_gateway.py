"""Cross-module OAuth, SQLAlchemy, and telemetry adapter for Zotero."""

from __future__ import annotations

from datetime import UTC

from app.database.telemetry import track_event
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportStatusItem,
    ZoteroImportStatusListResponse,
    ZoteroStatusResponse,
)
from app.modules.integrations.zotero.infrastructure.connection_repository import (
    zotero_connection_repository,
)
from app.modules.integrations.zotero.infrastructure.import_repository import (
    zotero_import_repository,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroCallback,
    ZoteroAccessToken,
    ZoteroCredentials,
    ZoteroRequestToken,
)
from app.shared.application import Actor
from sqlalchemy.orm import Session


class DefaultZoteroGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save_oauth_request(
        self,
        *,
        user_id: int,
        request_token: ZoteroRequestToken,
    ) -> None:
        zotero_connection_repository.delete_pending_for_user(
            db=self._db,
            user_id=user_id,
        )
        zotero_connection_repository.create_pending(
            db=self._db,
            user_id=user_id,
            oauth_token=request_token.token,
            oauth_token_secret=request_token.secret,
        )

    def oauth_callback(
        self,
        *,
        oauth_token: str,
    ) -> PreparedZoteroCallback | None:
        pending = zotero_connection_repository.get_pending_by_token(
            db=self._db,
            oauth_token=oauth_token,
        )
        if pending is None or pending.user_id is None:
            return None
        expires_at = pending.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return PreparedZoteroCallback(
            user_id=pending.user_id,
            request_token=ZoteroRequestToken(
                token=oauth_token,
                secret=pending.oauth_token_secret,
            ),
            expires_at=expires_at,
        )

    def discard_oauth_callback(self, *, oauth_token: str) -> None:
        pending = zotero_connection_repository.get_pending_by_token(
            db=self._db,
            oauth_token=oauth_token,
        )
        if pending is not None:
            zotero_connection_repository.delete_pending(
                db=self._db,
                pending=pending,
            )

    def save_connection(
        self,
        *,
        callback: PreparedZoteroCallback,
        access_token: ZoteroAccessToken,
    ) -> None:
        zotero_connection_repository.upsert_connection(
            db=self._db,
            user_id=callback.user_id,
            zotero_user_id=access_token.user_id,
            api_key=access_token.api_key,
        )
        self.discard_oauth_callback(
            oauth_token=callback.request_token.token,
        )
        track_event(
            "zotero_connected",
            user_id=str(callback.user_id),
            db=self._db,
        )

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

    def credentials(self, *, user_id: int) -> ZoteroCredentials | None:
        connection = zotero_connection_repository.get_by_user_id(
            self._db,
            user_id=user_id,
        )
        if connection is None:
            return None
        return ZoteroCredentials(
            user_id=str(connection.zotero_user_id),
            api_key=str(connection.api_key),
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
