"""Stable operation-journal actions owned by the Projects application."""

from app.modules.operation_journal.domain import OperationAction

PROJECT_COLLABORATOR_LEFT = OperationAction("project.collaborator_left")
PROJECT_COLLABORATOR_REMOVED = OperationAction("project.collaborator_removed")
PROJECT_COLLABORATOR_UPDATED = OperationAction("project.collaborator_updated")
PROJECT_CREATED = OperationAction("project.created")
PROJECT_DELETED = OperationAction("project.deleted")
PROJECT_INVITATION_ACCEPTED = OperationAction("project.invitation_accepted")
PROJECT_INVITATION_CREATED = OperationAction("project.invitation_created")
PROJECT_INVITATION_RESENT = OperationAction("project.invitation_resent")
PROJECT_INVITATION_REVOKED = OperationAction("project.invitation_revoked")
PROJECT_OWNERSHIP_TRANSFERRED = OperationAction("project.ownership_transferred")
PROJECT_PAPER_COLLECTED = OperationAction("project.paper_collected")
PROJECT_PAPER_REMOVED = OperationAction("project.paper_removed")
PROJECT_PAPERS_ADDED = OperationAction("project.papers_added")
PROJECT_UPDATED = OperationAction("project.updated")

__all__ = [
    "PROJECT_COLLABORATOR_LEFT",
    "PROJECT_COLLABORATOR_REMOVED",
    "PROJECT_COLLABORATOR_UPDATED",
    "PROJECT_CREATED",
    "PROJECT_DELETED",
    "PROJECT_INVITATION_ACCEPTED",
    "PROJECT_INVITATION_CREATED",
    "PROJECT_INVITATION_RESENT",
    "PROJECT_INVITATION_REVOKED",
    "PROJECT_OWNERSHIP_TRANSFERRED",
    "PROJECT_PAPER_COLLECTED",
    "PROJECT_PAPER_REMOVED",
    "PROJECT_PAPERS_ADDED",
    "PROJECT_UPDATED",
]
