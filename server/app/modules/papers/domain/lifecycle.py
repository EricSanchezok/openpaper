"""Pure canonical Document processing-state transitions."""

from __future__ import annotations

from app.shared.domain.enums import DocumentProcessingStatus


def can_begin_processing(current: DocumentProcessingStatus) -> bool:
    return current in {
        DocumentProcessingStatus.PENDING,
        DocumentProcessingStatus.FAILED,
    }


def can_complete_processing(current: DocumentProcessingStatus) -> bool:
    return current in {
        DocumentProcessingStatus.PENDING,
        DocumentProcessingStatus.PROCESSING,
        DocumentProcessingStatus.COMPLETED,
    }


def can_fail_processing(current: DocumentProcessingStatus) -> bool:
    return current is not DocumentProcessingStatus.COMPLETED
