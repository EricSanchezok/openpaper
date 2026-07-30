import datetime
from dataclasses import dataclass
from uuid import UUID

from app.database.models import ZoteroConnection, ZoteroOAuthPending
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

PENDING_TTL_MINUTES = 15


@dataclass(frozen=True, slots=True)
class ConnectionUpsert:
    connection: ZoteroConnection
    changed: bool


class ZoteroConnectionRepository:
    def create_pending(
        self,
        db: Session,
        *,
        user_id: int,
        oauth_token: str,
        oauth_token_secret: str,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> ZoteroOAuthPending:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=PENDING_TTL_MINUTES
        )
        db_obj = ZoteroOAuthPending(
            user_id=user_id,
            oauth_token=oauth_token,
            oauth_token_secret=oauth_token_secret,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            expires_at=expires_at,
        )
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    def get_pending_by_token(
        self, db: Session, *, oauth_token: str
    ) -> ZoteroOAuthPending | None:
        return db.scalars(
            select(ZoteroOAuthPending).where(
                ZoteroOAuthPending.oauth_token == oauth_token
            )
        ).first()

    def delete_pending(self, db: Session, *, pending: ZoteroOAuthPending) -> None:
        db.delete(pending)
        db.flush()

    def delete_pending_for_user(self, db: Session, *, user_id: int) -> None:
        db.execute(
            delete(ZoteroOAuthPending).where(ZoteroOAuthPending.user_id == user_id)
        )
        db.flush()

    def upsert_connection(
        self,
        db: Session,
        *,
        user_id: int,
        zotero_user_id: str,
        api_key: str,
    ) -> ConnectionUpsert:
        existing = self.get_by_user_id(db, user_id=user_id)
        if existing:
            normalized_user_id = str(zotero_user_id)
            normalized_api_key = str(api_key)
            changed = (
                existing.zotero_user_id != normalized_user_id
                or existing.api_key != normalized_api_key
            )
            if changed:
                existing.zotero_user_id = normalized_user_id
                existing.api_key = normalized_api_key
                db.add(existing)
                db.flush()
                db.refresh(existing)
            return ConnectionUpsert(connection=existing, changed=changed)

        db_obj = ZoteroConnection(
            user_id=user_id,
            zotero_user_id=zotero_user_id,
            api_key=api_key,
        )
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return ConnectionUpsert(connection=db_obj, changed=True)

    def get_by_user_id(self, db: Session, *, user_id: int) -> ZoteroConnection | None:
        return db.scalars(
            select(ZoteroConnection).where(ZoteroConnection.user_id == user_id)
        ).first()

    def delete_by_user_id(self, db: Session, *, user_id: int) -> UUID | None:
        connection = self.get_by_user_id(db, user_id=user_id)
        if not connection:
            return None
        connection_id = connection.id
        db.delete(connection)
        db.flush()
        return connection_id


zotero_connection_repository = ZoteroConnectionRepository()
