"""Framework-free paper domain rules."""

from .access import (
    DocumentAccessDecision,
    DocumentAccessScope,
    classify_document_access,
)
from .ingestion import (
    MAX_PDF_BYTES,
    MAX_PDF_SIZE_MB,
    content_sha256,
    durable_ingestion_key,
    normalize_idempotency_key,
)
from .lifecycle import (
    can_begin_processing,
    can_complete_processing,
    can_fail_processing,
)

__all__ = [
    "MAX_PDF_BYTES",
    "MAX_PDF_SIZE_MB",
    "DocumentAccessDecision",
    "DocumentAccessScope",
    "can_begin_processing",
    "can_complete_processing",
    "can_fail_processing",
    "classify_document_access",
    "content_sha256",
    "durable_ingestion_key",
    "normalize_idempotency_key",
]
