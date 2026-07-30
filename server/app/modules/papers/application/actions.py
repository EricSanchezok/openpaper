"""Stable operation-journal actions owned by the Papers application."""

from app.modules.operation_journal.domain import OperationAction

DOCUMENT_DELETED = OperationAction("document.deleted")
DOCUMENT_METADATA_HYDRATED = OperationAction("document.metadata_hydrated")
DOCUMENT_PROCESSING_COMPLETED = OperationAction("document.processing_completed")
DOCUMENT_PROCESSING_FAILED = OperationAction("document.processing_failed")
LIBRARY_PAPER_COLLECTED = OperationAction("library.paper_collected")
LIBRARY_PAPER_REMOVED = OperationAction("library.paper_removed")
LIBRARY_PAPER_SHARED = OperationAction("library.paper_shared")
LIBRARY_PAPER_UNSHARED = OperationAction("library.paper_unshared")
LIBRARY_PAPER_UPDATED = OperationAction("library.paper_updated")

__all__ = [
    "DOCUMENT_DELETED",
    "DOCUMENT_METADATA_HYDRATED",
    "DOCUMENT_PROCESSING_COMPLETED",
    "DOCUMENT_PROCESSING_FAILED",
    "LIBRARY_PAPER_COLLECTED",
    "LIBRARY_PAPER_REMOVED",
    "LIBRARY_PAPER_SHARED",
    "LIBRARY_PAPER_UNSHARED",
    "LIBRARY_PAPER_UPDATED",
]
