"""Cross-module deletion of generated storage objects without a database owner."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.database.models import JobOperation
from app.shared.domain import JsonValue
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class ScheduledStorageDeletion:
    job_id: uuid.UUID
    created: bool


def schedule_storage_deletion(
    db: Session,
    *,
    object_keys: Iterable[str],
    idempotency_key: str,
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> ScheduledStorageDeletion | None:
    keys = sorted({key for key in object_keys if key})
    if not keys:
        return None
    keys_json: list[JsonValue] = list(keys)
    job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    persisted = job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.STORAGE_DELETE,
            requested_by_id=None,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            idempotency_key=f"storage-delete:{idempotency_key}",
            payload={"object_keys": keys_json},
            task_name="delete_storage_objects",
            queue="storage_gc",
            task_kwargs={
                "object_keys": keys_json,
                "callback_url": (f"{base_url}/internal/v1/jobs/{job_id}/complete"),
                "claim_url": f"{base_url}/internal/v1/jobs/{job_id}/claim",
            },
            job_id=job_id,
        ),
    )
    return ScheduledStorageDeletion(
        job_id=persisted.job.id,
        created=persisted.created,
    )


__all__ = ["ScheduledStorageDeletion", "schedule_storage_deletion"]
