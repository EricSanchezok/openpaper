from __future__ import annotations

from app.helpers.s3 import s3_service


def test_presigned_url_keeps_the_provider_signed_host(monkeypatch) -> None:
    expected = (
        "https://bucket.s3.ap-southeast-1.amazonaws.com/uploads/paper.pdf"
        "?X-Amz-Signature=provider-signature"
    )

    def generate_presigned_url(*args, **kwargs) -> str:
        return expected

    monkeypatch.setattr(
        s3_service.s3_client,
        "generate_presigned_url",
        generate_presigned_url,
    )

    assert s3_service.generate_presigned_url("uploads/paper.pdf", 120) == expected
