import datetime

from app.database.models import ZoteroConnection, ZoteroOAuthPending
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

PENDING_TTL_MINUTES = 15


class CRUDZotero:
    def create_pending(
        self,
        db: Session,
        *,
        user_id: int,
        oauth_token: str,
        oauth_token_secret: str,
    ) -> ZoteroOAuthPending:
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=PENDING_TTL_MINUTES
        )
        db_obj = ZoteroOAuthPending(
            user_id=user_id,
            oauth_token=oauth_token,
            oauth_token_secret=oauth_token_secret,
            expires_at=expires_at,
        )
        db.add(db_obj)
        db.commit()
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
        db.commit()

    def delete_pending_for_user(self, db: Session, *, user_id: int) -> None:
        db.execute(
            delete(ZoteroOAuthPending).where(ZoteroOAuthPending.user_id == user_id)
        )
        db.commit()

    def upsert_connection(
        self,
        db: Session,
        *,
        user_id: int,
        zotero_user_id: str,
        api_key: str,
    ) -> ZoteroConnection:
        existing = self.get_by_user_id(db, user_id=user_id)
        if existing:
            existing.zotero_user_id = str(zotero_user_id)
            existing.api_key = str(api_key)
            db.add(existing)
            db.commit()
            db.refresh(existing)
            return existing

        db_obj = ZoteroConnection(
            user_id=user_id,
            zotero_user_id=zotero_user_id,
            api_key=api_key,
        )
        db.add(db_obj)
        db.commit()
        db.refresh(db_obj)
        return db_obj

    def get_by_user_id(self, db: Session, *, user_id: int) -> ZoteroConnection | None:
        return db.scalars(
            select(ZoteroConnection).where(ZoteroConnection.user_id == user_id)
        ).first()

    def delete_by_user_id(self, db: Session, *, user_id: int) -> bool:
        connection = self.get_by_user_id(db, user_id=user_id)
        if not connection:
            return False
        db.delete(connection)
        db.commit()
        return True


zotero_crud = CRUDZotero()
