from unittest.mock import MagicMock, patch

from app.integrations.jobs_client import JobsClient
from app.helpers.redaction import redact_url


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
    celery_app.send_task.side_effect = [MagicMock(id="task_pdf")]
    with patch(
        "app.integrations.jobs_client.Celery", return_value=celery_app
    ) as celery:
        client = JobsClient(
            celery_broker_url="amqp://user:password@rabbitmq:5672//",
        )
        assert client.publish_task(
            task_name="upload_and_process_file",
            queue="pdf_processing",
            job_id="job-pdf",
            kwargs={"s3_object_key": "documents/hash/source.pdf"},
        ) == "task_pdf"

    celery.assert_called_once()
    assert celery_app.send_task.call_count == 1
    assert celery_app.send_task.call_args_list[0].kwargs["task_id"] == "job-pdf"
