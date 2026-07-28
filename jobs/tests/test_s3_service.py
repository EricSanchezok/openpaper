from unittest.mock import patch

import pytest

from src.s3_service import S3Service


@pytest.mark.parametrize("variable", ["S3_BUCKET_NAME", "CLOUDFLARE_BUCKET_NAME"])
def test_s3_service_requires_bucket_configuration(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
) -> None:
    monkeypatch.delenv(variable, raising=False)

    with pytest.raises(RuntimeError, match=rf"{variable} must be configured"):
        S3Service()


def test_s3_service_builds_typed_client_from_complete_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S3_BUCKET_NAME", "scholens-test")
    monkeypatch.setenv(
        "CLOUDFLARE_BUCKET_NAME",
        "scholens-test.s3.example.invalid",
    )

    with patch("src.s3_service.boto3.client") as client:
        service = S3Service()

    assert service.bucket_name == "scholens-test"
    assert service.cloudflare_bucket_name == "scholens-test.s3.example.invalid"
    client.assert_called_once()


def test_generated_artifacts_use_the_exact_idempotent_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S3_BUCKET_NAME", "scholens-test")
    monkeypatch.setenv(
        "CLOUDFLARE_BUCKET_NAME",
        "scholens-test.s3.example.invalid",
    )
    with patch("src.s3_service.boto3.client") as client_factory:
        service = S3Service()

    key = service.upload_bytes_to_key(
        b"canonical markdown",
        "uploads/pdf-parses/job-1/full.md",
        "text/markdown; charset=utf-8",
    )

    assert key == "uploads/pdf-parses/job-1/full.md"
    client_factory.return_value.put_object.assert_called_once_with(
        Bucket="scholens-test",
        Key=key,
        Body=b"canonical markdown",
        ContentType="text/markdown; charset=utf-8",
    )
