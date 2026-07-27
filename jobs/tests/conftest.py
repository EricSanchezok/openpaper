"""Stable test-only configuration for Jobs service imports."""

import os

os.environ.setdefault("S3_BUCKET_NAME", "scholens-test")
os.environ.setdefault(
    "CLOUDFLARE_BUCKET_NAME",
    "scholens-test.s3.example.invalid",
)
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
