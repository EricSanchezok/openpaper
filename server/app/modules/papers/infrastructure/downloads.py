"""S3 adapter for signed paper downloads."""

from app.helpers.s3 import s3_service


class S3PaperDownloadSigner:
    def sign(self, *, storage_key: str) -> str:
        return s3_service.generate_presigned_url(storage_key)
