from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.database.models import (
    JsonValue,
    Document,
    ZoteroConnection,
    ZoteroImportedItem,
    ZoteroImportSource,
    ZoteroImportStatus,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ZoteroImportChange:
    item: ZoteroImportedItem
    changed: bool


class ZoteroImportRepository:
    def get_by_item_key(
        self, db: Session, *, user_id: int, zotero_item_key: str
    ) -> ZoteroImportedItem | None:
        return db.scalars(
            select(ZoteroImportedItem).where(
                ZoteroImportedItem.user_id == user_id,
                ZoteroImportedItem.zotero_item_key == zotero_item_key,
            )
        ).first()

    def get_by_upload_job_id(
        self, db: Session, *, upload_job_id: UUID
    ) -> ZoteroImportedItem | None:
        return db.scalars(
            select(ZoteroImportedItem).where(
                ZoteroImportedItem.upload_job_id == upload_job_id
            )
        ).first()

    def get_max_last_synced_at(self, db: Session, *, user_id: int) -> datetime | None:
        return db.scalar(
            select(func.max(ZoteroImportedItem.last_synced_at)).where(
                ZoteroImportedItem.user_id == user_id
            )
        )

    def get_auto_import_since(self, db: Session, *, user_id: int) -> datetime | None:
        return db.scalar(
            select(func.max(ZoteroImportedItem.created_at)).where(
                ZoteroImportedItem.user_id == user_id,
                ZoteroImportedItem.status == ZoteroImportStatus.COMPLETED,
            )
        )

    def completed_item_keys(self, db: Session, *, user_id: int) -> set[str]:
        return set(
            db.scalars(
                select(ZoteroImportedItem.zotero_item_key).where(
                    ZoteroImportedItem.user_id == user_id,
                    ZoteroImportedItem.status == ZoteroImportStatus.COMPLETED,
                    ZoteroImportedItem.document_id.isnot(None),
                )
            ).all()
        )

    def list_recent_by_user(
        self, db: Session, *, user_id: int, limit: int = 20
    ) -> list[tuple[ZoteroImportedItem, str | None]]:
        statement = (
            select(ZoteroImportedItem, Document.title)
            .outerjoin(Document, ZoteroImportedItem.document_id == Document.id)
            .where(ZoteroImportedItem.user_id == user_id)
            .order_by(ZoteroImportedItem.created_at.desc())
            .limit(limit)
        )
        return list(db.execute(statement).tuples().all())

    def list_by_item_keys(
        self, db: Session, *, user_id: int, item_keys: list[str]
    ) -> list[tuple[ZoteroImportedItem, str | None]]:
        if not item_keys:
            return []
        statement = (
            select(ZoteroImportedItem, Document.title)
            .outerjoin(Document, ZoteroImportedItem.document_id == Document.id)
            .where(
                ZoteroImportedItem.user_id == user_id,
                ZoteroImportedItem.zotero_item_key.in_(item_keys),
            )
            .order_by(ZoteroImportedItem.created_at.desc())
        )
        return list(db.execute(statement).tuples().all())

    def create(
        self,
        db: Session,
        *,
        user_id: int,
        zotero_item_key: str,
        import_source: str,
        zotero_attachment_key: str | None = None,
        source_url: str | None = None,
        document_id: UUID | None = None,
        upload_job_id: UUID | None = None,
        annotations_payload: list[dict[str, JsonValue]] | None = None,
        status: str = ZoteroImportStatus.PROCESSING,
        last_synced_at: datetime | None = None,
    ) -> ZoteroImportedItem:
        db_obj = ZoteroImportedItem(
            user_id=user_id,
            zotero_item_key=zotero_item_key,
            zotero_attachment_key=zotero_attachment_key,
            import_source=import_source,
            source_url=source_url,
            document_id=document_id,
            upload_job_id=upload_job_id,
            annotations_payload=annotations_payload,
            status=status,
            last_synced_at=last_synced_at,
        )
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    def update_status(
        self,
        db: Session,
        *,
        item: ZoteroImportedItem,
        status: str,
        error_message: str | None = None,
        document_id: UUID | None = None,
    ) -> ZoteroImportChange:
        changed = item.status != status
        if error_message is not None and item.error_message != error_message:
            changed = True
        if document_id is not None and item.document_id != document_id:
            changed = True
        if not changed:
            return ZoteroImportChange(item=item, changed=False)
        item.status = status
        if error_message is not None:
            item.error_message = error_message
        if document_id is not None:
            item.document_id = document_id
        db.add(item)
        db.flush()
        db.refresh(item)
        return ZoteroImportChange(item=item, changed=True)

    def list_syncable_by_user(
        self, db: Session, *, user_id: int, limit: int
    ) -> list[ZoteroImportedItem]:
        return list(
            db.scalars(
                select(ZoteroImportedItem)
                .join(Document, ZoteroImportedItem.document_id == Document.id)
                .where(
                    ZoteroImportedItem.user_id == user_id,
                    ZoteroImportedItem.status == ZoteroImportStatus.COMPLETED,
                    ZoteroImportedItem.document_id.isnot(None),
                    ZoteroImportedItem.import_source
                    == ZoteroImportSource.PDF_ATTACHMENT,
                    ZoteroImportedItem.zotero_attachment_key.isnot(None),
                )
                .order_by(
                    ZoteroImportedItem.last_synced_at.asc().nullsfirst(),
                    ZoteroImportedItem.created_at.desc(),
                )
                .limit(limit)
            ).all()
        )

    def list_user_ids_due_for_sync(
        self, db: Session, *, threshold_hours: float = 24
    ) -> list[int]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=threshold_hours)

        rows = db.scalars(
            select(ZoteroImportedItem.user_id)
            # Only users who still have a live Zotero connection are syncable.
            # Imported items survive a disconnect (the papers stay in the
            # library), so without this join we'd surface disconnected users as
            # "due for sync" and fail on the missing connection.
            .join(
                ZoteroConnection,
                ZoteroConnection.user_id == ZoteroImportedItem.user_id,
            )
            .where(
                ZoteroImportedItem.status == ZoteroImportStatus.COMPLETED,
                ZoteroImportedItem.import_source == ZoteroImportSource.PDF_ATTACHMENT,
                ZoteroImportedItem.zotero_attachment_key.isnot(None),
                or_(
                    ZoteroImportedItem.last_synced_at.is_(None),
                    ZoteroImportedItem.last_synced_at < cutoff,
                ),
            )
            .distinct()
        ).all()

        return list(rows)

    def finalize_processing_import(
        self,
        db: Session,
        *,
        item: ZoteroImportedItem,
        import_source: str,
        zotero_attachment_key: str | None,
        source_url: str | None,
        document_id: UUID,
        upload_job_id: UUID,
        annotations_payload: list[dict[str, JsonValue]] | None,
        last_synced_at: datetime | None = None,
    ) -> ZoteroImportChange:
        changed = (
            item.import_source != import_source
            or item.zotero_attachment_key != zotero_attachment_key
            or item.source_url != source_url
            or item.document_id != document_id
            or item.upload_job_id != upload_job_id
            or item.annotations_payload != annotations_payload
            or item.error_message is not None
            or (last_synced_at is not None and item.last_synced_at != last_synced_at)
        )
        if not changed:
            return ZoteroImportChange(item=item, changed=False)
        item.import_source = import_source
        item.zotero_attachment_key = zotero_attachment_key
        item.source_url = source_url
        item.document_id = document_id
        item.upload_job_id = upload_job_id
        item.annotations_payload = annotations_payload
        item.error_message = None
        if last_synced_at is not None:
            item.last_synced_at = last_synced_at
        db.add(item)
        db.flush()
        db.refresh(item)
        return ZoteroImportChange(item=item, changed=True)

    def update_after_sync(
        self,
        db: Session,
        *,
        item: ZoteroImportedItem,
        annotations_payload: list[dict[str, JsonValue]] | None,
        last_synced_at: datetime,
    ) -> ZoteroImportChange:
        changed = (
            item.annotations_payload != annotations_payload
            or item.last_synced_at != last_synced_at
        )
        if not changed:
            return ZoteroImportChange(item=item, changed=False)
        item.annotations_payload = annotations_payload
        item.last_synced_at = last_synced_at
        db.add(item)
        db.flush()
        db.refresh(item)
        return ZoteroImportChange(item=item, changed=True)


zotero_import_repository = ZoteroImportRepository()
