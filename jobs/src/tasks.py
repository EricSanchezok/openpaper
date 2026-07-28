"""
Celery tasks for Scholens jobs
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from functools import partial
from typing import Any

import psutil
import requests

from src.schemas import DataTableSchema
from src.data_table_processor import construct_data_table
from src.pdf.models import (
    ParserConfigurationError,
    ParserContentError,
    ParserError,
    ParserSecurityError,
    ParserTransientError,
)
from src.pdf.pipeline import process_pdf_file, upgrade_pdf_from_checkpoint
from src.pdf.state import ParserStateStore
from src.celery_app import celery_app, ZOTERO_SYNC_INTERVAL_SECONDS
from src.s3_service import s3_service
from src.token_usage import collect_token_usage
from src.utils import time_it
from src.webhook_signing import post_signed_json

logger = logging.getLogger(__name__)

PARSER_UPGRADE_INITIAL_DELAY_SECONDS = 30
PARSER_UPGRADE_MAX_RETRIES = 16
PARSER_UPGRADE_MAX_RETRY_DELAY_SECONDS = 15 * 60


def _update_status(task: Any, task_id: str, status: str) -> None:
    logger.info("Updating task %s status: %s", task_id, status)
    try:
        task.update_state(state="PROGRESS", meta={"status": status})
    except Exception:
        logger.exception("Failed to update task %s status", task_id)


def _deliver_webhook(
    webhook_url: str,
    payload: dict[str, Any],
    *,
    task_id: str,
) -> bool:
    try:
        response = post_signed_json(webhook_url, payload, timeout=60)
        response.raise_for_status()
        logger.info("Webhook sent successfully for task %s", task_id)
        return True
    except requests.RequestException:
        logger.exception("Failed to send webhook for task %s", task_id)
        return False


def _parser_upgrade_webhook_url(webhook_url: str) -> str:
    marker = "/paper-processing/"
    if marker not in webhook_url:
        raise ValueError("paper processing webhook URL has an invalid path")
    return webhook_url.replace(marker, "/paper-parser-upgrade/", 1)


def _schedule_parser_upgrade(*, job_id: str, webhook_url: str) -> None:
    upgrade_pdf_parser.apply_async(
        kwargs={
            "job_id": job_id,
            "webhook_url": _parser_upgrade_webhook_url(webhook_url),
        },
        countdown=PARSER_UPGRADE_INITIAL_DELAY_SECONDS,
        task_id=f"{job_id}:mineru-upgrade",
        queue="pdf_processing",
    )
    logger.info(
        "Scheduled resumable MinerU upgrade",
        extra={"job_id": job_id, "phase": "upgrade_schedule"},
    )


@celery_app.task(bind=True, name="upload_and_process_file")
def upload_and_process_file(
    self,
    s3_object_key: str,
    webhook_url: str,
    skip_metadata_extraction: bool = False,
) -> dict[str, Any]:
    """
    Process a PDF file from S3 object key and send results to webhook.

    When skip_metadata_extraction is True, the LLM metadata/summary step is
    skipped and only deterministic outputs (preview, raw text, page offsets)
    are produced. Used by the Zotero import path.
    """
    task_id = self.request.id
    usage_events: list[dict[str, Any]] = []
    write_to_status = partial(_update_status, self, task_id)

    try:
        logger.info("Starting PDF processing for task %s", task_id)
        write_to_status("Downloading PDF from S3")

        async def download_with_timer():
            async with time_it("Downloading PDF from S3", job_id=task_id):
                return s3_service.download_file_to_bytes(s3_object_key)

        pdf_bytes = asyncio.run(download_with_timer())
        source_url = s3_service.generate_presigned_download_url(
            s3_object_key,
            expiration_seconds=int(os.getenv("MINERU_SOURCE_URL_TTL_SECONDS", "900")),
        )

        write_to_status("Processing PDF file")

        with collect_token_usage(task_id) as usage:
            usage_events = usage.events
            result = asyncio.run(
                process_pdf_file(
                    pdf_bytes,
                    source_url,
                    s3_object_key,
                    task_id,
                    status_callback=write_to_status,
                    skip_metadata_extraction=skip_metadata_extraction,
                )
            )

        write_to_status("PDF processing complete!")

        webhook_payload = {
            "task_id": task_id,
            "status": "completed" if result.success else "failed",
            "result": result.model_dump(),
            "error": result.error if not result.success else None,
            "usage_events": usage_events,
        }

        webhook_delivered = _deliver_webhook(
            webhook_url,
            webhook_payload,
            task_id=task_id,
        )
        if not webhook_delivered:
            webhook_payload["webhook_error"] = "webhook_delivery_failed"
        elif result.parser_upgrade_pending:
            _schedule_parser_upgrade(job_id=task_id, webhook_url=webhook_url)
        elif result.parser_backend == "mineru" and result.parser_quality == "full":
            try:
                asyncio.run(_clear_parser_checkpoint(task_id))
            except ParserTransientError as exc:
                logger.warning(
                    "Could not clear completed MinerU checkpoint; diagnostics=%s",
                    exc.diagnostic_fields(),
                    extra={"job_id": task_id, **exc.diagnostic_fields()},
                )

        logger.info("Task %s completed", task_id)
        return webhook_payload

    except Exception as exc:
        diagnostics = (
            exc.diagnostic_fields()
            if isinstance(exc, ParserError)
            else {"exception_type": type(exc).__name__}
        )
        logger.exception(
            "PDF processing task failed; diagnostics=%s",
            diagnostics,
            extra={"job_id": task_id, **diagnostics},
        )
        failure_payload = {
            "task_id": task_id,
            "status": "failed",
            "result": {
                "success": False,
                "job_id": task_id,
                "error": "pdf_processing_failed",
            },
            "error": "pdf_processing_failed",
            "usage_events": usage_events,
        }
        _deliver_webhook(webhook_url, failure_payload, task_id=task_id)
        raise


async def _clear_parser_checkpoint(job_id: str) -> None:
    state_store = ParserStateStore()
    try:
        await state_store.clear(job_id)
    finally:
        await state_store.close()


@celery_app.task(
    bind=True,
    name="upgrade_pdf_parser",
    max_retries=PARSER_UPGRADE_MAX_RETRIES,
    soft_time_limit=900,
    time_limit=960,
)
def upgrade_pdf_parser(
    self,
    job_id: str,
    webhook_url: str,
) -> dict[str, Any]:
    """Resume a MinerU checkpoint and atomically upgrade a text-only paper."""
    task_id = self.request.id
    try:
        result = asyncio.run(upgrade_pdf_from_checkpoint(job_id))
        payload = {
            "task_id": task_id,
            "result": result.model_dump(),
        }
        if not _deliver_webhook(webhook_url, payload, task_id=task_id):
            raise ParserTransientError(
                "Parser upgrade webhook delivery failed",
                phase="webhook",
                task_id=task_id,
            )
        asyncio.run(_clear_parser_checkpoint(job_id))
        logger.info(
            "MinerU parser upgrade completed",
            extra={"job_id": job_id, "task_id": task_id, "phase": "upgrade"},
        )
        return payload
    except ParserTransientError as exc:
        retry_number = int(self.request.retries) + 1
        countdown = min(
            PARSER_UPGRADE_MAX_RETRY_DELAY_SECONDS,
            PARSER_UPGRADE_INITIAL_DELAY_SECONDS * (2 ** min(retry_number - 1, 5)),
        )
        logger.warning(
            "MinerU parser upgrade remains pending; diagnostics=%s",
            exc.diagnostic_fields(),
            extra={
                "job_id": job_id,
                **exc.diagnostic_fields(),
                "retry_number": retry_number,
                "retry_in_seconds": countdown,
            },
        )
        raise self.retry(exc=exc, countdown=countdown) from exc
    except ParserContentError as exc:
        logger.warning(
            "MinerU parser upgrade reached a terminal content state; diagnostics=%s",
            exc.diagnostic_fields(),
            extra={"job_id": job_id, **exc.diagnostic_fields()},
        )
        asyncio.run(_clear_parser_checkpoint(job_id))
        return {"task_id": task_id, "status": "terminal"}
    except (ParserConfigurationError, ParserSecurityError) as exc:
        logger.error(
            "MinerU parser upgrade stopped at a fail-closed boundary; diagnostics=%s",
            exc.diagnostic_fields(),
            extra={"job_id": job_id, **exc.diagnostic_fields()},
            exc_info=True,
        )
        raise
    except ParserError as exc:
        logger.error(
            "MinerU parser upgrade failed; diagnostics=%s",
            exc.diagnostic_fields(),
            extra={"job_id": job_id, **exc.diagnostic_fields()},
            exc_info=True,
        )
        raise


@celery_app.task(
    bind=True, name="process_data_table", soft_time_limit=900, time_limit=960
)
def construct_data_table_task(
    self, data_table: DataTableSchema, webhook_url: str
) -> None:
    """
    Celery task to construct a data table based on the provided schema.
    """
    task_id = self.request.id
    usage_events: list[dict[str, Any]] = []
    write_to_status = partial(_update_status, self, task_id)

    write_to_status("Starting data table construction")

    try:
        data_table = DataTableSchema.model_validate(data_table)
        with collect_token_usage(task_id) as usage:
            usage_events = usage.events
            result = asyncio.run(
                construct_data_table(
                    data_table_schema=data_table,
                    status_callback=write_to_status,
                )
            )

        write_to_status("Data table construction complete!")

        webhook_payload = {
            "task_id": task_id,
            "status": "completed" if result.success else "failed",
            "result": result.model_dump(),
            "error": None,
            "usage_events": usage_events,
        }

        if not _deliver_webhook(webhook_url, webhook_payload, task_id=task_id):
            webhook_payload["webhook_error"] = "webhook_delivery_failed"

        logger.info("Task %s completed", task_id)
        return

    except Exception:
        logger.exception("Data table construction task %s failed", task_id)
        failure_payload = {
            "task_id": task_id,
            "status": "failed",
            "result": None,
            "error": "data_table_processing_failed",
            "usage_events": usage_events,
        }

        _deliver_webhook(webhook_url, failure_payload, task_id=task_id)
        raise


@celery_app.task(bind=True, name="health_check")
def health_check(self):
    """
    Health check task to monitor worker status.
    Returns system metrics and worker health status.
    """
    try:
        # Get system metrics
        memory_info = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        disk_usage = psutil.disk_usage("/")

        # Get process info
        process = psutil.Process(os.getpid())
        process_memory = process.memory_info()

        health_data = {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "worker_id": self.request.hostname,
            "task_id": self.request.id,
            "system_metrics": {
                "memory_percent": memory_info.percent,
                "memory_available_mb": memory_info.available / (1024 * 1024),
                "cpu_percent": cpu_percent,
                "disk_percent": disk_usage.percent,
            },
            "process_metrics": {
                "memory_mb": process_memory.rss / (1024 * 1024),
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
            },
        }

        # Check if worker is unhealthy
        if (
            memory_info.percent > 90
            or cpu_percent > 95
            or process_memory.rss / (1024 * 1024) > 1500
        ):
            health_data["status"] = "unhealthy"
            health_data["alert"] = "High resource usage detected"

        return health_data

    except Exception:
        logger.exception("Health check failed")
        return {
            "status": "unhealthy",
            "error": "health_check_failed",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "worker_id": self.request.hostname,
        }


@celery_app.task(bind=True, name="periodic_zotero_sync")
def periodic_zotero_sync(self):
    """
    Periodic task that triggers the server to sync new Zotero annotations
    for all users whose items haven't been synced in the past 24 hours.
    Fires at the interval configured by ZOTERO_SYNC_INTERVAL_SECONDS (default 24h).
    """
    webhook_base = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")
    sync_interval = int(ZOTERO_SYNC_INTERVAL_SECONDS)
    url = f"{webhook_base}/api/webhooks/internal/zotero-sync-all?threshold_seconds={sync_interval}"
    logger.info(f"Triggering periodic Zotero sync via {url}")
    resp = post_signed_json(url, timeout=120)
    resp.raise_for_status()
    result = resp.json()
    logger.info(
        f"Periodic Zotero sync complete: {result.get('synced_users', 0)} users synced"
    )

    # Celery's task-success log runs the return value through a bounded saferepr,
    # which collapses nested lists to "[...]" — so per-user sync errors never show
    # up there. Log them explicitly here where they won't be truncated.
    for user_result in result.get("results", []):
        user_errors = user_result.get("errors") or []
        if user_errors:
            logger.warning(
                "Zotero sync errors for user %s: %s",
                user_result.get("user_id"),
                json.dumps(user_errors),
            )

    return result
