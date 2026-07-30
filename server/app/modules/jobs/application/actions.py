"""Stable OperationJournal actions owned by the Jobs module."""

from app.modules.operation_journal.domain import OperationAction

JOB_CREATED = OperationAction("job.created")
JOB_COMPLETED = OperationAction("job.completed")
JOB_FAILED = OperationAction("job.failed")

__all__ = ["JOB_COMPLETED", "JOB_CREATED", "JOB_FAILED"]
