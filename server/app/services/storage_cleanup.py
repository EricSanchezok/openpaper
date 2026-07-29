"""Durable deletion of generated S3 objects that have no database owner."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from app.database.models import JobOperation
from app.shared.domain import JsonValue
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from sqlalchemy.orm import Session


def schedule_storage_deletion(
    db: Session,
    *,
    object_keys: Iterable[str],
    idempotency_key: str,
) -> uuid.UUID | None:
    keys = sorted({key for key in object_keys if key})
    if not keys:
        return None
    keys_json: list[JsonValue] = list(keys)
    job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.STORAGE_DELETE,
            requested_by_id=None,
            idempotency_key=f"storage-delete:{idempotency_key}",
            payload={"object_keys": keys_json},
            task_name="delete_storage_objects",
            queue="storage_gc",
            task_kwargs={
                "object_keys": keys_json,
                "callback_url": (
                    f"{base_url}/api/webhooks/jobs/{job_id}/storage-delete"
                ),
                "claim_url": f"{base_url}/api/webhooks/jobs/{job_id}/claim",
            },
            job_id=job_id,
        ),
    )
    return job_id
