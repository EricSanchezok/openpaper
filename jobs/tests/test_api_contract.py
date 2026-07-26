from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from src.app import app


def test_jobs_api_exposes_only_health_and_status(monkeypatch) -> None:
    result = SimpleNamespace(
        state="SUCCESS",
        result={"success": True},
        info=None,
        date_done=datetime.now(timezone.utc),
    )
    monkeypatch.setattr("src.app.AsyncResult", lambda _task_id, **_kwargs: result)
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
    monkeypatch.setattr("src.app.AsyncResult", lambda _task_id, **_kwargs: result)

    response = TestClient(app).get("/task/task-2/status")
    assert response.status_code == 200
    assert response.json()["error"] == "task_failed"
    assert "internal-host" not in response.text


def test_task_success_rejects_non_object_result(monkeypatch) -> None:
    result = SimpleNamespace(
        state="SUCCESS",
        result="unexpected",
        info=None,
        date_done=datetime.now(timezone.utc),
    )
    monkeypatch.setattr("src.app.AsyncResult", lambda _task_id, **_kwargs: result)

    response = TestClient(app).get("/task/task-3/status")
    assert response.status_code == 500
    assert response.json()["detail"] == "task_status_failed"
