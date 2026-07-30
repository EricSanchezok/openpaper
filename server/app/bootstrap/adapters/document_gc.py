"""Cross-module delayed, reference-safe cleanup for canonical documents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.database.models import (
    Conversation,
    ConversationScopeType,
    Document,
    LibraryPaper,
    ProjectPaper,
    JobOperation,
    ResearchAudioOverview,
    ResearchItem,
)
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from app.bootstrap.adapters.storage_cleanup import (
    ScheduledStorageDeletion,
    schedule_storage_deletion,
)
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

DOCUMENT_GC_GRACE_PERIOD = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class ScheduledDocumentGc:
    job_id: uuid.UUID
    created: bool


def _has_references(db: Session, *, document_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                or_(
                    exists(
                        select(LibraryPaper.id).where(
                            LibraryPaper.document_id == document_id
                        )
                    ),
                    exists(
                        select(ProjectPaper.id).where(
                            ProjectPaper.document_id == document_id
                        )
                    ),
                )
            )
        )
    )


def schedule_document_gc(
    db: Session,
    *,
    document_id: uuid.UUID,
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
    now: datetime | None = None,
) -> ScheduledDocumentGc | None:
    document = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        return None
    if _has_references(db, document_id=document_id):
        document.gc_after = None
        return None
    document.gc_after = (now or datetime.now(timezone.utc)) + DOCUMENT_GC_GRACE_PERIOD
    job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    persisted = job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.DOCUMENT_GC,
            requested_by_id=None,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            document_id=document.id,
            idempotency_key=(
                f"document-gc:{document.id}:{document.gc_after.isoformat()}"
            ),
            payload={"document_id": str(document.id)},
            task_name="collect_document",
            queue="storage_gc",
            task_kwargs={
                "callback_url": (f"{base_url}/internal/v1/jobs/{job_id}/complete"),
                "claim_url": f"{base_url}/internal/v1/jobs/{job_id}/claim",
            },
            job_id=job_id,
            available_at=document.gc_after,
        ),
    )
    return ScheduledDocumentGc(
        job_id=persisted.job.id,
        created=persisted.created,
    )


@dataclass(frozen=True, slots=True)
class DocumentGcResult:
    document_id: uuid.UUID
    deleted: bool
    cancelled: bool
    storage_deletion: ScheduledStorageDeletion | None = None


def collect_document_if_due(
    db: Session,
    *,
    document_id: uuid.UUID,
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
    now: datetime | None = None,
) -> DocumentGcResult:
    current_time = now or datetime.now(timezone.utc)
    document = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        return DocumentGcResult(document_id, deleted=True, cancelled=False)
    if _has_references(db, document_id=document_id):
        document.gc_after = None
        return DocumentGcResult(document_id, deleted=False, cancelled=True)
    if document.gc_after is None or document.gc_after > current_time:
        return DocumentGcResult(document_id, deleted=False, cancelled=False)

    object_keys = {
        document.s3_object_key,
        document.preview_s3_key,
        document.parser_markdown_s3_key,
        document.parser_archive_s3_key,
        *db.scalars(
            select(ResearchAudioOverview.s3_object_key)
            .join(
                ResearchItem,
                ResearchItem.id == ResearchAudioOverview.research_item_id,
            )
            .where(ResearchItem.document_id == document_id)
        ).all(),
    }
    storage_deletion = schedule_storage_deletion(
        db,
        object_keys=(key for key in object_keys if key),
        idempotency_key=f"document:{document_id}",
        origin_operation_id=origin_operation_id,
        correlation_id=correlation_id,
    )

    db.execute(
        update(Conversation)
        .where(
            Conversation.scope_type == ConversationScopeType.PAPER.value,
            Conversation.document_id == document_id,
        )
        .values(
            scope_label_snapshot=func.coalesce(
                Conversation.scope_label_snapshot,
                document.title,
                document.original_filename,
            ),
            context_deleted_at=current_time,
        )
    )
    db.delete(document)
    db.flush()
    return DocumentGcResult(
        document_id,
        deleted=True,
        cancelled=False,
        storage_deletion=storage_deletion,
    )


def list_due_document_ids(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[uuid.UUID]:
    current_time = now or datetime.now(timezone.utc)
    return list(
        db.scalars(
            select(Document.id)
            .where(
                Document.gc_after.isnot(None),
                Document.gc_after <= current_time,
            )
            .order_by(Document.gc_after.asc())
            .limit(limit)
        ).all()
    )


__all__ = [
    "DOCUMENT_GC_GRACE_PERIOD",
    "DocumentGcResult",
    "ScheduledDocumentGc",
    "collect_document_if_due",
    "list_due_document_ids",
    "schedule_document_gc",
]
