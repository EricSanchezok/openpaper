from unittest.mock import MagicMock, patch

import requests
from app.integrations.jobs_client import JobsClient
from app.helpers.redaction import redact_url
from app.schemas.responses import DataTableSchema


def test_redact_url_removes_credentials_and_sensitive_query_values() -> None:
    redacted = redact_url(
        "amqp://scholens:super-secret@rabbitmq:5672/vhost?token=abc&mode=fast"
    )

    assert "scholens" not in redacted
    assert "super-secret" not in redacted
    assert "abc" not in redacted
    assert "rabbitmq:5672" in redacted
    assert "mode=fast" in redacted


def test_jobs_client_reuses_one_configured_celery_producer() -> None:
    celery_app = MagicMock()
    celery_app.send_task.side_effect = [
        MagicMock(id="task_pdf"),
        MagicMock(id="task_table"),
    ]
    with patch(
        "app.integrations.jobs_client.Celery", return_value=celery_app
    ) as celery:
        client = JobsClient(
            webhook_base_url="http://server:8000",
            celery_broker_url="amqp://user:password@rabbitmq:5672//",
            celery_api_url="http://jobs-api:8001",
        )
        assert (
            client.submit_pdf_processing_job("papers/test.pdf", "job-pdf") == "task_pdf"
        )

        table = DataTableSchema(columns=[], papers=[])
        assert (
            client.submit_data_table_processing_job(table, "job-table") == "task_table"
        )

    celery.assert_called_once()
    assert celery_app.send_task.call_count == 2
    assert celery_app.send_task.call_args_list[0].kwargs["task_id"] == "job-pdf"
    assert celery_app.send_task.call_args_list[1].kwargs["task_id"] == "job-table"


def test_jobs_status_failure_returns_stable_public_error() -> None:
    with patch("app.integrations.jobs_client.Celery"):
        client = JobsClient(
            webhook_base_url="http://server:8000",
            celery_broker_url="amqp://user:password@rabbitmq:5672//",
            celery_api_url="http://jobs-api:8001",
        )

    with patch(
        "app.integrations.jobs_client.requests.get",
        side_effect=requests.ConnectionError(
            "HTTPConnectionPool(host='jobs-api', port=8001)"
        ),
    ):
        result = client.check_celery_task_status("task-1")

    assert result == {
        "task_id": "task-1",
        "status": "API_ERROR",
        "error": "jobs_service_unavailable",
    }
