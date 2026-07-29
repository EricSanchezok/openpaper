"""Private S3 object storage for canonical documents and research output.

Object keys are stable domain identifiers. Signed URLs are deliberately
ephemeral and are never persisted in PostgreSQL.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")

DOCUMENT_PREFIX = "documents"
RESEARCH_PREFIX = "research"
DEFAULT_SIGNED_URL_TTL_SECONDS = 900


def document_source_key(sha256: str) -> str:
    return f"{DOCUMENT_PREFIX}/{sha256}/source.pdf"


def document_preview_key(sha256: str) -> str:
    return f"{DOCUMENT_PREFIX}/{sha256}/preview.webp"


def document_markdown_key(sha256: str) -> str:
    return f"{DOCUMENT_PREFIX}/{sha256}/canonical.md"


def document_archive_key(sha256: str) -> str:
    return f"{DOCUMENT_PREFIX}/{sha256}/mineru-result.zip"


def research_audio_key(item_id: str, extension: str) -> str:
    safe_extension = extension.lower().lstrip(".")
    if not safe_extension.isalnum():
        raise ValueError("invalid_audio_extension")
    return f"{RESEARCH_PREFIX}/audio/{item_id}.{safe_extension}"


class S3Service:
    def __init__(self) -> None:
        self.s3_client: S3Client = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            ),
        )
        self.bucket_name = S3_BUCKET_NAME or ""

    def _require_bucket(self) -> str:
        if not self.bucket_name:
            raise RuntimeError("S3_BUCKET_NAME is required")
        return self.bucket_name

    def upload_bytes(
        self,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
    ) -> str:
        if not data:
            raise ValueError("cannot_upload_empty_object")
        try:
            self.s3_client.put_object(
                Bucket=self._require_bucket(),
                Key=object_key,
                Body=data,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
        except ClientError as exc:
            logger.exception("S3 upload failed for %s", object_key)
            raise RuntimeError("s3_upload_failed") from exc
        return object_key

    def upload_document_source(self, *, sha256: str, pdf_bytes: bytes) -> str:
        return self.upload_bytes(
            object_key=document_source_key(sha256),
            data=pdf_bytes,
            content_type="application/pdf",
        )

    def upload_path(
        self,
        *,
        file_path: str,
        object_key: str,
        content_type: str,
    ) -> str:
        path = Path(file_path)
        if not path.is_file():
            raise ValueError("storage_source_file_not_found")
        try:
            with path.open("rb") as source:
                self.s3_client.upload_fileobj(
                    source,
                    self._require_bucket(),
                    object_key,
                    ExtraArgs={
                        "ContentType": content_type,
                        "ServerSideEncryption": "AES256",
                    },
                )
        except ClientError as exc:
            logger.exception("S3 upload failed for %s", object_key)
            raise RuntimeError("s3_upload_failed") from exc
        return object_key

    async def upload_file(
        self,
        file: BytesIO,
        filename: str,
        *,
        object_key: str | None = None,
    ) -> str:
        """Upload a stream to an explicit private key.

        This narrow async wrapper remains for call sites that already run in an
        async flow. Canonical PDF ingestion should use ``upload_document_source``.
        """
        if object_key is None:
            raise ValueError("object_key_is_required")
        file.seek(0)
        data = file.read()
        content_type = (
            "application/pdf"
            if filename.lower().endswith(".pdf")
            else "application/octet-stream"
        )
        return self.upload_bytes(
            object_key=object_key,
            data=data,
            content_type=content_type,
        )

    def delete_file(self, object_key: str) -> bool:
        try:
            self.s3_client.delete_object(
                Bucket=self._require_bucket(),
                Key=object_key,
            )
            return True
        except ClientError:
            logger.exception("S3 delete failed for %s", object_key)
            return False

    def delete_files(self, object_keys: Iterable[str]) -> list[str]:
        failed: list[str] = []
        for object_key in dict.fromkeys(object_keys):
            if object_key and not self.delete_file(object_key):
                failed.append(object_key)
        return failed

    def download_bytes(self, object_key: str) -> bytes:
        try:
            response = self.s3_client.get_object(
                Bucket=self._require_bucket(),
                Key=object_key,
            )
            body = response.get("Body")
            if body is None:
                raise RuntimeError("s3_object_body_missing")
            data = body.read()
            if not isinstance(data, bytes):
                raise TypeError("s3_object_body_invalid")
            return data
        except ClientError as exc:
            logger.exception("S3 download failed for %s", object_key)
            raise RuntimeError("s3_download_failed") from exc

    def object_size_bytes(self, object_key: str) -> int:
        try:
            response = self.s3_client.head_object(
                Bucket=self._require_bucket(),
                Key=object_key,
            )
        except ClientError as exc:
            logger.exception("S3 head failed for %s", object_key)
            raise RuntimeError("s3_head_failed") from exc
        content_length = response.get("ContentLength")
        if content_length is None:
            raise RuntimeError("s3_content_length_missing")
        return int(content_length)

    def generate_presigned_url(
        self,
        object_key: str,
        expiration: int = DEFAULT_SIGNED_URL_TTL_SECONDS,
    ) -> str:
        if expiration < 60 or expiration > 3600:
            raise ValueError("signed_url_ttl_out_of_range")
        try:
            return str(
                self.s3_client.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": self._require_bucket(),
                        "Key": object_key,
                    },
                    ExpiresIn=expiration,
                )
            )
        except ClientError as exc:
            logger.exception("S3 signing failed for %s", object_key)
            raise RuntimeError("s3_signing_failed") from exc

    def generate_presigned_urls(
        self,
        object_keys: dict[str, str],
        expiration: int = DEFAULT_SIGNED_URL_TTL_SECONDS,
    ) -> dict[str, str]:
        return {
            identifier: self.generate_presigned_url(key, expiration)
            for identifier, key in object_keys.items()
        }


s3_service = S3Service()
