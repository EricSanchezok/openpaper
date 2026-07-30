"""Stable OperationJournal actions owned by the Zotero module."""

from app.modules.operation_journal.domain import OperationAction

ZOTERO_CONNECTION_CONNECTED = OperationAction("zotero.connection_connected")
ZOTERO_CONNECTION_DISCONNECTED = OperationAction("zotero.connection_disconnected")
ZOTERO_IMPORT_STARTED = OperationAction("zotero.import_started")
ZOTERO_IMPORT_COMPLETED = OperationAction("zotero.import_completed")
ZOTERO_IMPORT_FAILED = OperationAction("zotero.import_failed")
ZOTERO_ANNOTATIONS_SYNCED = OperationAction("zotero.annotations_synced")

__all__ = [
    "ZOTERO_ANNOTATIONS_SYNCED",
    "ZOTERO_CONNECTION_CONNECTED",
    "ZOTERO_CONNECTION_DISCONNECTED",
    "ZOTERO_IMPORT_COMPLETED",
    "ZOTERO_IMPORT_FAILED",
    "ZOTERO_IMPORT_STARTED",
]
