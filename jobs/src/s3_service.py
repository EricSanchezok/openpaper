"""
S3 service for file uploads and management.
"""

import logging
import os
from typing import Literal, cast

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from mypy_boto3_s3 import S3Client

logger = logging.getLogger(__name__)

# Load AWS configuration from environment variables
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _s3_addressing_style() -> Literal["auto", "virtual", "path"]:
    value = os.environ.get("AWS_S3_ADDRESSING_STYLE", "virtual")
    if value not in {"auto", "virtual", "path"}:
        raise ValueError("AWS_S3_ADDRESSING_STYLE must be auto, virtual, or path")
    return cast(Literal["auto", "virtual", "path"], value)


AWS_S3_ADDRESSING_STYLE = _s3_addressing_style()


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


class S3Service:
    """Service for handling S3 operations"""

    def __init__(self) -> None:
        """Initialize S3 client"""
        self.bucket_name = _required_env("S3_BUCKET_NAME")
        self.cloudflare_bucket_name = _required_env("CLOUDFLARE_BUCKET_NAME")
        self.s3_client: S3Client = boto3.client(
            "s3",
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=AWS_REGION,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": AWS_S3_ADDRESSING_STYLE},
                connect_timeout=10,
                read_timeout=60,
                retries={"mode": "standard", "total_max_attempts": 3},
            ),
        )

    def download_file_to_bytes(self, object_key: str) -> bytes:
        """Download a file from S3 and return its content as bytes

        Args:
            object_key (str): The S3 object key to download

        Returns:
            bytes: The file content as bytes

        Raises:
            ClientError: If the file cannot be downloaded from S3
        """
        try:
            logger.info("s3.object.download_started")
            response = self.s3_client.get_object(
                Bucket=self.bucket_name, Key=object_key
            )
            return response["Body"].read()
        except (BotoCoreError, ClientError):
            logger.exception("s3.object.download_failed")
            raise

    def upload_bytes_to_key(
        self,
        file_bytes: bytes,
        object_key: str,
        content_type: str,
    ) -> str:
        """Idempotently write generated content to a deterministic S3 key."""
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=object_key,
            Body=file_bytes,
            ContentType=content_type,
        )
        return object_key

    def delete_file(self, object_key: str) -> bool:
        """
        Delete a file from S3

        Args:
            object_key: The S3 object key to delete

        Returns:
            bool: True if deleted successfully, False otherwise
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except ClientError:
            logger.exception("s3.object.delete_failed")
            return False


# Create a single instance to use throughout the application
s3_service = S3Service()
