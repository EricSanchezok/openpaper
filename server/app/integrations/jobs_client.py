"""Celery transport client for the standalone Scholens Jobs service."""

import logging
from typing import Any

import requests
from app.helpers.celery_config import (
    get_celery_api_url,
    get_celery_broker_url,
    get_webhook_base_url,
)
from app.helpers.redaction import redact_url
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class JobsClient:
    """Client for submitting processing jobs to the separate Celery service."""

    def __init__(
        self,
        webhook_base_url: str | None = None,
        celery_broker_url: str | None = None,
        celery_api_url: str | None = None,
    ):
        """
        Initialize the client.

        Args:
            webhook_base_url: The base URL where your app receives webhooks
                             (e.g., "https://your-app.com")
            celery_broker_url: Redis/RabbitMQ URL where Celery tasks are queued
            celery_api_url: Base URL of the Celery API service for status checks
                           (e.g., "http://localhost:8001")
        """
        self.webhook_base_url = get_webhook_base_url(webhook_base_url)
        self.celery_broker_url = get_celery_broker_url(celery_broker_url)
        self.celery_api_url = get_celery_api_url(celery_api_url)
        self._celery_app = Celery(
            "scholens_tasks",
            broker=self.celery_broker_url,
        )
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
    ) -> str:
        """Publish one durable outbox record with broker confirmation enabled."""
        try:
            task = self._celery_app.send_task(
                task_name,
                kwargs=kwargs,
                queue=queue,
                task_id=job_id,
            )
            return str(task.id)
        except Exception as exc:
            error_text = str(exc)
            if "ACCESS_REFUSED" in error_text:
                raise RuntimeError("jobs_broker_authentication_failed") from exc
            if "Connection refused" in error_text or "111" in error_text:
                raise RuntimeError("jobs_broker_unavailable") from exc
            raise RuntimeError("jobs_publish_failed") from exc

    def submit_pdf_processing_job(
        self,
        s3_object_key: str,
        job_id: str,
        skip_metadata_extraction: bool = False,
    ) -> str:
        """
        Submit a PDF processing job to the separate Celery service.

        Args:
            s3_object_key: The S3 object key for the PDF file
            job_id: Your internal job ID for tracking
            skip_metadata_extraction: When True, the worker skips LLM metadata
                extraction and only produces preview/text/page offsets. Used by
                the Zotero import path.

        Returns:
            str: Celery task ID

        Raises:
            ImportError: If Celery is not available
            Exception: If task submission fails
        """
        # Validate input data
        if s3_object_key is None:
            raise ValueError("s3_object_key cannot be None")
        if not isinstance(s3_object_key, str):
            raise ValueError(f"s3_object_key must be str, got {type(s3_object_key)}")
        if len(s3_object_key) == 0:
            raise ValueError("s3_object_key cannot be empty")

        logger.info("Submitting PDF processing job %s", job_id)

        # Connect to Celery broker directly to submit task
        try:
            # Build webhook URL that includes your job ID
            webhook_url = (
                f"{self.webhook_base_url}/api/webhooks/paper-processing/{job_id}"
            )
            # Submit the task to the queue (the separate jobs service will pick it up)
            task = self._celery_app.send_task(
                "upload_and_process_file",  # Task name as registered by the worker
                kwargs={
                    "s3_object_key": s3_object_key,
                    "webhook_url": webhook_url,
                    "skip_metadata_extraction": skip_metadata_extraction,
                },
                # Explicit: the server's Celery instance has no task_routes, so we
                # must pin the queue here. Must match what the worker's `-Q` set
                # contains (see jobs/scripts/start_worker.sh).
                queue="pdf_processing",
                task_id=job_id,
            )

            logger.info("Submitted PDF processing task %s for job %s", task.id, job_id)
            return str(task.id)
        except Exception as e:
            error_msg = str(e)
            if "ACCESS_REFUSED" in error_msg:
                logger.error(
                    "Message broker authentication failed for %s",
                    redact_url(self.celery_broker_url),
                )
                raise RuntimeError("jobs_broker_authentication_failed") from e
            if "Connection refused" in error_msg or "111" in error_msg:
                logger.error(
                    "Message broker unavailable at %s",
                    redact_url(self.celery_broker_url),
                )
                raise RuntimeError("jobs_broker_unavailable") from e
            logger.exception("Failed to submit PDF processing job %s", job_id)
            raise RuntimeError("jobs_submission_failed") from e

    def check_celery_task_status(self, task_id: str) -> dict[str, Any]:
        """
        Check the status of a Celery task using the HTTP API.

        Args:
            task_id: The Celery task ID to check

        Returns:
            Dict containing task status information
        """
        try:
            # Make HTTP request to the Celery API service
            response = requests.get(
                f"{self.celery_api_url}/task/{task_id}/status", timeout=10
            )
            response.raise_for_status()

            task_status = response.json()

            # Transform the API response to match our expected format
            return {
                "task_id": task_status.get("task_id", task_id),
                "status": task_status.get("status", "unknown"),
                "result": task_status.get("result"),
                "meta": task_status.get("meta"),
                "error": task_status.get("error"),
                "progress": task_status.get("progress"),
                "progress_message": task_status.get("progress_message"),
            }

        except requests.exceptions.RequestException:
            logger.warning(
                "Jobs status API unavailable at %s",
                redact_url(self.celery_api_url),
            )
            return {
                "task_id": task_id,
                "status": "API_ERROR",
                "error": "jobs_service_unavailable",
            }
        except Exception:
            logger.exception("Unexpected failure checking task %s", task_id)
            return {
                "task_id": task_id,
                "status": "ERROR",
                "error": "task_status_failed",
            }


# Create a client instance to use throughout the application
jobs_client = JobsClient()
