from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from src.app import app, celery_app


def test_jobs_api_exposes_only_health_and_status(monkeypatch) -> None:
    result = SimpleNamespace(
        state="SUCCESS",
        result={"success": True},
        info=None,
        date_done=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(celery_app, "AsyncResult", lambda _task_id: result)
    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "healthy",
        "service": "pdf-processing",
    }

    status = client.get("/task/task-1/status")
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["result"] == {"success": True}

    assert client.delete("/task/task-1").status_code == 404
    assert client.get("/worker/status").status_code == 404


def test_task_failure_uses_stable_error_code(monkeypatch) -> None:
    result = SimpleNamespace(
        state="FAILURE",
        result=None,
        info=RuntimeError("redis://secret@internal-host:6379"),
        date_done=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(celery_app, "AsyncResult", lambda _task_id: result)

    response = TestClient(app).get("/task/task-2/status")
    assert response.status_code == 200
    assert response.json()["error"] == "task_failed"
    assert "internal-host" not in response.text
