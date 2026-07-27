from __future__ import annotations

from app.helpers.s3 import s3_service


def test_s3_client_uses_sigv4_virtual_hosted_urls() -> None:
    assert s3_service.s3_client.meta.config.signature_version == "s3v4"
    assert s3_service.s3_client.meta.config.s3["addressing_style"] == "virtual"


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


def test_presigned_url_can_be_generated_from_stored_object_url(monkeypatch) -> None:
    generated: list[tuple[str, int]] = []

    def generate_presigned_url(object_key: str, expiration: int) -> str:
        generated.append((object_key, expiration))
        return "https://signed.example.invalid/preview"

    monkeypatch.setattr(s3_service, "generate_presigned_url", generate_presigned_url)

    result = s3_service.generate_presigned_url_from_storage_url(
        "https://bucket.s3.example.invalid/uploads/paper%20preview.png",
        expiration=600,
    )

    assert result == "https://signed.example.invalid/preview"
    assert generated == [("uploads/paper preview.png", 600)]


def test_invalid_stored_object_url_is_not_signed(monkeypatch) -> None:
    def generate_presigned_url(*_args, **_kwargs) -> str:
        raise AssertionError("invalid URLs must not be signed")

    monkeypatch.setattr(s3_service, "generate_presigned_url", generate_presigned_url)

    assert (
        s3_service.generate_presigned_url_from_storage_url(
            "http://bucket.example.invalid/uploads/preview.png"
        )
        is None
    )
