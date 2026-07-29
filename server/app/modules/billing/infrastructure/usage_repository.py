"""Logical paper and storage usage billed to a Scholens account."""

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    LibraryPaper,
    Project,
    ProjectPaper,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class ResourceUsageRepository:
    def completed_reference_count(self, db: Session, *, user_id: int) -> int:
        library_count = int(
            db.scalar(
                select(func.count(LibraryPaper.id))
                .join(Document, Document.id == LibraryPaper.document_id)
                .where(
                    LibraryPaper.user_id == user_id,
                    Document.processing_status
                    == DocumentProcessingStatus.COMPLETED.value,
                )
            )
            or 0
        )
        project_count = int(
            db.scalar(
                select(func.count(ProjectPaper.id))
                .join(Document, Document.id == ProjectPaper.document_id)
                .join(Project, Project.id == ProjectPaper.project_id)
                .where(
                    Project.owner_id == user_id,
                    Document.processing_status
                    == DocumentProcessingStatus.COMPLETED.value,
                )
            )
            or 0
        )
        return library_count + project_count

    def completed_storage_kb(self, db: Session, *, user_id: int) -> int:
        library_bytes = int(
            db.scalar(
                select(func.coalesce(func.sum(Document.size_bytes), 0))
                .join(LibraryPaper, LibraryPaper.document_id == Document.id)
                .where(
                    LibraryPaper.user_id == user_id,
                    Document.processing_status
                    == DocumentProcessingStatus.COMPLETED.value,
                )
            )
            or 0
        )
        project_bytes = int(
            db.scalar(
                select(func.coalesce(func.sum(Document.size_bytes), 0))
                .join(ProjectPaper, ProjectPaper.document_id == Document.id)
                .join(Project, Project.id == ProjectPaper.project_id)
                .where(
                    Project.owner_id == user_id,
                    Document.processing_status
                    == DocumentProcessingStatus.COMPLETED.value,
                )
            )
            or 0
        )
        return (library_bytes + project_bytes + 1023) // 1024


resource_usage_repository = ResourceUsageRepository()
