"""Celery producer used exclusively by the durable Jobs outbox."""

from __future__ import annotations

from typing import Any

from app.helpers.celery_config import get_celery_broker_url
from celery import Celery


class JobsClient:
    """Publish already-persisted work with broker confirmation enabled."""

    def __init__(self, celery_broker_url: str | None = None) -> None:
        self.celery_broker_url = get_celery_broker_url(celery_broker_url)
        self._celery_app = Celery("scholens_tasks", broker=self.celery_broker_url)
        self._celery_app.conf.update(
            broker_connection_retry_on_startup=True,
            broker_connection_retry=True,
            broker_connection_max_retries=3,
            broker_transport_options={"confirm_publish": True},
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            task_always_eager=False,
            task_publish_retry=True,
            task_publish_retry_policy={
                "max_retries": 3,
                "interval_start": 0.2,
                "interval_step": 0.5,
                "interval_max": 2.0,
            },
        )

    def publish_task(
        self,
        *,
        task_name: str,
        queue: str,
        job_id: str,
        kwargs: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> str:
        try:
            task = self._celery_app.send_task(
                task_name,
                kwargs=kwargs,
                queue=queue,
                task_id=job_id,
                headers=headers,
            )
            return str(task.id)
        except Exception as exc:
            error_text = str(exc)
            if "ACCESS_REFUSED" in error_text:
                raise RuntimeError("jobs_broker_authentication_failed") from exc
            if "Connection refused" in error_text or "111" in error_text:
                raise RuntimeError("jobs_broker_unavailable") from exc
            raise RuntimeError("jobs_publish_failed") from exc


jobs_client = JobsClient()
