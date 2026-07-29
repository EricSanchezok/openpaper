"""Billing-backed capacity adapters shared by business use cases."""

from uuid import UUID

from app.modules.billing.infrastructure.quotas import (
    can_user_create_project,
    can_user_upload_paper,
    require_library_document_capacity,
)
from app.modules.papers.infrastructure.models import Document
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from sqlalchemy.orm import Session


class BillingLibraryCapacity:
    def __init__(self, db: Session) -> None:
        self._db = db

    def require(self, *, actor: Actor, document_id: UUID) -> None:
        document = self._db.get(Document, document_id)
        if document is None:
            raise RuntimeError("shared_document_disappeared")
        require_library_document_capacity(
            self._db,
            user=actor,
            document=document,
        )


class BillingProjectCapacity:
    def __init__(self, db: Session) -> None:
        self._db = db

    def require_create(self, *, actor: Actor) -> None:
        can_create, _reason = can_user_create_project(self._db, actor)
        if not can_create:
            raise AppError(
                code="project_quota_exceeded",
                message="Project creation limit reached",
                kind=FailureKind.PERMISSION_DENIED,
            )


class BillingZoteroImportCapacity:
    def __init__(self, db: Session) -> None:
        self._db = db

    def require(self, *, actor: Actor) -> None:
        allowed, reason = can_user_upload_paper(self._db, actor)
        if not allowed:
            raise AppError(
                code="paper_quota_exceeded",
                message=reason or "Upload limit reached",
                kind=FailureKind.PERMISSION_DENIED,
            )
