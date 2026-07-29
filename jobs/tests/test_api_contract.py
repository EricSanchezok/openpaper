from pathlib import Path

from fastapi.testclient import TestClient
from src.app import app
from src.celery_app import celery_app
from src.tasks import upload_and_process_file


def test_jobs_api_exposes_only_health() -> None:
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "healthy",
        "service": "scholens-jobs",
    }

    assert client.get("/task/task-1/status").status_code == 404
    assert client.delete("/task/task-1").status_code == 404
    assert client.get("/worker/status").status_code == 404


def test_worker_has_no_referral_task_or_queue() -> None:
    task_routes = celery_app.conf.task_routes
    worker_script = (
        Path(__file__).parents[1] / "scripts" / "start_worker.sh"
    ).read_text(encoding="utf-8")

    assert "delayed_referral_settlement_callback" not in task_routes
    assert "user_processing" not in worker_script


def test_pdf_task_budget_reserves_time_after_mineru_retries() -> None:
    worker_script = (
        Path(__file__).parents[1] / "scripts" / "start_worker.sh"
    ).read_text(encoding="utf-8")

    task_routes = celery_app.conf.task_routes
    assert task_routes
    assert "upgrade_pdf_parser" not in task_routes
    assert upload_and_process_file.soft_time_limit == 1200
    assert upload_and_process_file.time_limit == 1260
    assert "--soft-time-limit=900" in worker_script
    assert "--time-limit=960" in worker_script
