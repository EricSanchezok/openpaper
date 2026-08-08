"""
Celery application configuration and setup.
"""

import os
from datetime import timedelta

from dotenv import load_dotenv
from celery import Celery
from src.pdf import validate_pdf_runtime_configuration
from src.observability import configure_jobs_observability

load_dotenv()  # Load environment variables from .env file
configure_jobs_observability()
validate_pdf_runtime_configuration()

BROKER_URL = os.getenv("CELERY_BROKER_URL", "pyamqp://guest@127.0.0.1:55672//")
BACKEND_URL = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:56379/0")

# Create Celery instance
celery_app = Celery(
    "scholens_tasks", broker=BROKER_URL, backend=BACKEND_URL, include=["src.tasks"]
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,  # Results expire after 1 hour
    task_routes={
        "upload_and_process_file": {"queue": "pdf_processing"},
        "postprocess_pdf": {"queue": "pdf_processing"},
        "collect_document": {"queue": "storage_gc"},
        "delete_storage_objects": {"queue": "storage_gc"},
        "generate_audio_overview": {"queue": "audio"},
        "process_data_table": {"queue": "data_table"},
        "periodic_zotero_sync": {"queue": "zotero_sync"},
        "postprocess_zotero": {"queue": "zotero_sync"},
    },
    worker_prefetch_multiplier=1,  # Process one task at a time
    task_acks_late=True,
    reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    worker_max_tasks_per_child=1000,
    # Health monitoring settings
    worker_send_task_events=True,
    task_send_sent_event=True,
    worker_hijack_root_logger=False,
    worker_log_color=False,
    # Worker heartbeat and timeout settings
    broker_heartbeat=30,
    broker_heartbeat_checkrate=2.0,
    worker_disable_rate_limits=True,
    # Memory and resource limits
    worker_max_memory_per_child=500000,  # 500MB in KB
)

celery_app.autodiscover_tasks()

ZOTERO_SYNC_INTERVAL_SECONDS = int(
    os.getenv("ZOTERO_SYNC_INTERVAL_SECONDS", str(24 * 60 * 60))
)

celery_app.conf.beat_schedule = {
    "periodic-zotero-sync": {
        "task": "periodic_zotero_sync",
        "schedule": timedelta(seconds=ZOTERO_SYNC_INTERVAL_SECONDS),
        "options": {"queue": "zotero_sync"},
    },
}

if __name__ == "__main__":
    celery_app.start()
