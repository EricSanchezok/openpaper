"""Cross-module project-document persistence adapter."""

import uuid
from datetime import datetime, timezone

from app.database.models import (
    Document,
    DurableJob,
    JobStatus,
    LibraryPaper,
    UploadReservation,
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.shared.domain import AppError
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.billing.infrastructure.quotas import (
    require_library_document_capacity,
    require_project_document_capacity,
)
from app.modules.projects.infrastructure.access import (
    require_project_access,
    require_project_permission,
)
from app.shared.application import Actor
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, load_only


class ProjectDocumentRepository:
    def attach_library_documents(
        self,
        db: Session,
        *,
        document_ids: list[uuid.UUID],
        project_id: uuid.UUID,
        user: Actor,
    ) -> tuple[list[ProjectPaper], int]:
        """Atomically attach new Library documents and report duplicate count."""
        require_project_permission(
            db,
            project_id=project_id,
            user_id=user.id,
            permission="manage_papers",
        )
        # Serialize membership, transfer, and paper mutations on this Project.
        project = db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        if project is None:
            raise AppError(
                code="project_not_found",
                message="Project not found",
                status_code=404,
            )

        unique_ids = list(dict.fromkeys(document_ids))
        existing_ids = set(
            db.scalars(
                select(ProjectPaper.document_id).where(
                    ProjectPaper.project_id == project_id,
                    ProjectPaper.document_id.in_(unique_ids),
                )
            ).all()
        )
        new_ids = [
            document_id for document_id in unique_ids if document_id not in existing_ids
        ]
        if not new_ids:
            return [], len(unique_ids)

        documents = list(
            db.scalars(
                select(Document)
                .join(LibraryPaper, LibraryPaper.document_id == Document.id)
                .where(
                    Document.id.in_(new_ids),
                    LibraryPaper.user_id == user.id,
                )
            ).all()
        )
        found_ids = {document.id for document in documents}
        if found_ids != set(new_ids):
            raise AppError(
                code="library_document_not_found",
                message="Every new document must exist in your Library",
                status_code=404,
            )

        require_project_document_capacity(
            db,
            owner_id=project.owner_id,
            project_id=project_id,
            documents=documents,
        )
        associations = [
            ProjectPaper(
                project_id=project_id,
                document_id=document.id,
                added_by_id=user.id,
            )
            for document in documents
        ]
        db.add_all(associations)
        db.execute(
            update(Document)
            .where(
                Document.id.in_(new_ids),
                Document.gc_after.isnot(None),
            )
            .values(gc_after=None)
        )
        project.updated_at = datetime.now(timezone.utc)
        db.flush()
        for association in associations:
            db.refresh(association)
        return associations, len(existing_ids)

    def attach_reserved_upload(
        self,
        db: Session,
        *,
        document: Document,
        upload_job: UploadReservation,
        project_id: uuid.UUID,
        user: Actor,
    ) -> tuple[ProjectPaper, bool]:
        """Attach a fresh upload covered by its durable Project reservation."""
        access = require_project_permission(
            db,
            project_id=project_id,
            user_id=user.id,
            permission="manage_papers",
        )
        reservation = db.scalar(
            select(UploadReservation.id)
            .join(DurableJob, DurableJob.id == UploadReservation.id)
            .where(
                UploadReservation.id == upload_job.id,
                DurableJob.project_id == project_id,
                DurableJob.requested_by_id == user.id,
                DurableJob.status.in_((JobStatus.PENDING, JobStatus.RUNNING)),
            )
        )
        if reservation is None:
            raise AppError(
                code="upload_reservation_invalid",
                message="The Project upload reservation is no longer valid",
                status_code=409,
            )
        reference = document_repository.attach_project(
            db,
            project_id=project_id,
            document_id=document.id,
            added_by_id=user.id,
        )
        access.project.updated_at = datetime.now(timezone.utc)
        db.flush()
        association = db.scalar(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.document_id == document.id,
            )
        )
        if association is None:
            raise RuntimeError("project_document_attachment_missing")
        return association, reference.created

    def get_paper_by_project(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        project_id: uuid.UUID,
        user: Actor,
    ) -> Document | None:
        require_project_access(db, project_id=project_id, user_id=user.id)

        project_paper = db.scalars(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.document_id == document_id,
            )
        ).first()

        if not project_paper:
            return None

        return db.get(Document, project_paper.document_id)

    def get_all_papers_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: Actor
    ) -> list[Document]:
        require_project_access(db, project_id=project_id, user_id=user.id)

        document_ids = db.scalars(
            select(ProjectPaper.document_id).where(
                ProjectPaper.project_id == project_id
            )
        ).all()
        papers = db.scalars(select(Document).where(Document.id.in_(document_ids))).all()
        return list(papers)

    def get_papers_metadata_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: Actor
    ) -> list[Document]:
        """
        Lightweight variant of get_all_papers_by_project_id for the project
        papers listing endpoint.

        Loads only the columns needed to render the list and to generate
        presigned URLs, deliberately avoiding heavy columns such as
        raw_content, ts_vector, summary, summary_citations and
        page_offset_map. Those columns can be megabytes per row and were
        previously fetched and discarded on every list request.
        """
        require_project_access(db, project_id=project_id, user_id=user.id)

        papers = db.scalars(
            select(Document)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(ProjectPaper.project_id == project_id)
            .options(
                load_only(
                    Document.title,
                    Document.abstract,
                    Document.authors,
                    Document.institutions,
                    Document.journal,
                    Document.publisher,
                    Document.doi,
                    Document.publish_date,
                    Document.created_at,
                    Document.s3_object_key,
                    Document.preview_s3_key,
                    Document.size_bytes,
                )
            )
        ).all()
        return list(papers)

    def get_library_document_ids(
        self,
        db: Session,
        *,
        document_ids: list[uuid.UUID],
        user: Actor,
    ) -> list[uuid.UUID]:
        if not document_ids:
            return []
        return list(
            db.scalars(
                select(LibraryPaper.document_id).where(
                    LibraryPaper.user_id == user.id,
                    LibraryPaper.document_id.in_(document_ids),
                )
            ).all()
        )

    def get_project_document_ids_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: Actor
    ) -> list[uuid.UUID]:
        require_project_access(db, project_id=project_id, user_id=user.id)

        return list(
            db.scalars(
                select(ProjectPaper.document_id).where(
                    ProjectPaper.project_id == project_id
                )
            ).all()
        )

    def get_paper_count_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: Actor
    ) -> int:
        """Number of papers in a project. Returns 0 if the user has no access."""
        require_project_permission(
            db,
            project_id=project_id,
            user_id=user.id,
            permission="manage_papers",
        )

        return int(
            db.scalar(
                select(func.count(ProjectPaper.id)).where(
                    ProjectPaper.project_id == project_id
                )
            )
            or 0
        )

    def remove_by_paper_and_project(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        project_id: uuid.UUID,
        user: Actor,
    ) -> ProjectPaper | None:
        require_project_permission(
            db,
            project_id=project_id,
            user_id=user.id,
            permission="manage_papers",
        )

        project_paper = db.scalars(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.document_id == document_id,
            )
        ).first()

        if project_paper is None:
            raise AppError(
                code="project_document_not_found",
                message="Document not found in this Project",
                status_code=404,
            )

        db.delete(project_paper)
        db.flush()
        from app.modules.papers.infrastructure.garbage_collection import (
            schedule_document_gc,
        )

        schedule_document_gc(db, document_id=document_id)
        db.flush()
        return project_paper

    def get_projects_by_document_id(
        self, db: Session, *, document_id: uuid.UUID, user: Actor
    ) -> list[Project]:
        # First, find all project-paper associations for the given document_id
        project_ids = db.scalars(
            select(ProjectPaper.project_id).where(
                ProjectPaper.document_id == document_id
            )
        ).all()

        if not project_ids:
            return []

        # Now, fetch all projects that match these IDs and that the user has access to
        projects = db.scalars(
            select(Project)
            .outerjoin(
                ProjectCollaborator,
                Project.id == ProjectCollaborator.project_id,
            )
            .where(
                Project.id.in_(project_ids),
                or_(
                    Project.owner_id == user.id,
                    ProjectCollaborator.user_id == user.id,
                ),
            )
            .distinct()
        ).all()
        return list(projects)

    def add_project_paper_to_library(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        project_id: uuid.UUID,
        current_user: Actor,
    ) -> Document | None:
        document = self.get_paper_by_project(
            db,
            document_id=document_id,
            project_id=project_id,
            user=current_user,
        )
        if document is None:
            return None
        existing = db.scalar(
            select(LibraryPaper).where(
                LibraryPaper.document_id == document.id,
                LibraryPaper.user_id == current_user.id,
            )
        )
        if existing is not None:
            return document
        require_library_document_capacity(
            db,
            user=current_user,
            document=document,
        )
        document_repository.attach_library(
            db,
            document_id=document.id,
            user_id=current_user.id,
        )
        db.flush()
        return document


project_document_repository = ProjectDocumentRepository()
