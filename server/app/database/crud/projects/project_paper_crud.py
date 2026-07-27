import logging
import uuid

from app.database.crud.paper_crud import paper_crud
from app.database.models import (
    Document,
    LibraryPaper,
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.policies.projects import get_project_access
from app.repositories.projects import project_repository
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, load_only

logger = logging.getLogger(__name__)


class ProjectPaperBase(BaseModel):
    paper_id: uuid.UUID


class ProjectPaperCreate(ProjectPaperBase):
    pass


class ProjectPaperUpdate(BaseModel):  # Empty update schema
    pass


class ProjectPaperCRUD:
    @staticmethod
    def _has_project_access(
        db: Session, *, project_id: uuid.UUID, user_id: int
    ) -> bool:
        return (
            get_project_access(db, project_id=project_id, user_id=user_id) is not None
        )

    def create(
        self,
        db: Session,
        *,
        obj_in: ProjectPaperCreate,
        user: CurrentUser | None = None,
        project_id: uuid.UUID | None = None,
        auto_commit: bool = True,
    ) -> ProjectPaper | None:
        # Validate required parameters for this implementation
        if user is None:
            raise ValueError("user parameter is required for ProjectPaperCRUD.create")
        if project_id is None:
            raise ValueError(
                "project_id parameter is required for ProjectPaperCRUD.create"
            )

        try:
            # Check if the user has permission to add a paper to this project
            access = get_project_access(db, project_id=project_id, user_id=user.id)
            if access is None or not access.can_manage_papers:
                logger.warning(
                    f"User {user.id} does not have permission to add paper to project {project_id}"
                )
                return None

            # A user can add a paper they have deliberately collected in their
            # personal library. Project-only access is not enough to copy a
            # document between projects implicitly.
            paper = db.scalars(
                select(Document)
                .join(LibraryPaper, LibraryPaper.document_id == Document.id)
                .where(
                    Document.id == obj_in.paper_id,
                    LibraryPaper.user_id == user.id,
                )
            ).first()
            if not paper:
                logger.warning(
                    f"Document with id {obj_in.paper_id} not found for user {user.id}"
                )
                return None

            return self.attach_document(
                db,
                document=paper,
                project_id=project_id,
                user=user,
                auto_commit=auto_commit,
            )
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error creating {ProjectPaper.__name__}: {str(e)}", exc_info=True
            )
            return None

    def attach_document(
        self,
        db: Session,
        *,
        document: Document,
        project_id: uuid.UUID,
        user: CurrentUser,
        auto_commit: bool = True,
    ) -> ProjectPaper | None:
        """Attach an already-authorized document to a project.

        This internal boundary is also used for a fresh project upload, which
        deliberately has no personal ``LibraryPaper`` entry.
        """
        access = get_project_access(db, project_id=project_id, user_id=user.id)
        if access is None or not access.can_manage_papers:
            return None
        existing = db.scalar(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.document_id == document.id,
            )
        )
        if existing is not None:
            return existing
        association = ProjectPaper(
            project_id=project_id,
            document_id=document.id,
            added_by_id=user.id,
        )
        db.add(association)
        if auto_commit:
            db.commit()
        else:
            db.flush()
        db.refresh(association)
        project_repository.touch(db, project_id=project_id, commit=auto_commit)
        return association

    def get_paper_by_project(
        self,
        db: Session,
        *,
        paper_id: uuid.UUID,
        project_id: uuid.UUID,
        user: CurrentUser,
    ) -> Document | None:
        access = get_project_access(db, project_id=project_id, user_id=user.id)
        if access is None:
            return None

        project_paper = db.scalars(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.document_id == paper_id,
            )
        ).first()

        if not project_paper:
            return None

        return db.get(Document, project_paper.document_id)

    def get_all_papers_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: CurrentUser
    ) -> list[Document]:
        # First, check if the user has access to the project.
        if not self._has_project_access(db, project_id=project_id, user_id=user.id):
            return []

        paper_ids = db.scalars(
            select(ProjectPaper.document_id).where(
                ProjectPaper.project_id == project_id
            )
        ).all()
        papers = db.scalars(select(Document).where(Document.id.in_(paper_ids))).all()
        return list(papers)

    def get_papers_metadata_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: CurrentUser
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
        # First, check if the user has access to the project.
        if not self._has_project_access(db, project_id=project_id, user_id=user.id):
            return []

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
                    # Needed by s3_service.get_cached_presigned_urls_bulk
                    Document.s3_object_key,
                    Document.cached_presigned_url,
                    Document.presigned_url_expires_at,
                    Document.size_in_kb,
                )
            )
        ).all()
        return list(papers)

    def get_library_document_ids(
        self,
        db: Session,
        *,
        document_ids: list[uuid.UUID],
        user: CurrentUser,
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

    def get_project_paper_ids_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: CurrentUser
    ) -> list[uuid.UUID]:
        # First, check if the user has access to the project.
        if not self._has_project_access(db, project_id=project_id, user_id=user.id):
            return []

        return list(
            db.scalars(
                select(ProjectPaper.document_id).where(
                    ProjectPaper.project_id == project_id
                )
            ).all()
        )

    def get_paper_count_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: CurrentUser
    ) -> int:
        """Number of papers in a project. Returns 0 if the user has no access."""
        access = get_project_access(db, project_id=project_id, user_id=user.id)
        if access is None or not access.can_manage_papers:
            return 0

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
        paper_id: uuid.UUID,
        project_id: uuid.UUID,
        user: CurrentUser,
    ) -> ProjectPaper | None:
        access = get_project_access(db, project_id=project_id, user_id=user.id)
        if access is None or not access.can_manage_papers:
            return None

        project_paper = db.scalars(
            select(ProjectPaper).where(
                ProjectPaper.project_id == project_id,
                ProjectPaper.document_id == paper_id,
            )
        ).first()

        if not project_paper:
            return None

        db.delete(project_paper)
        db.commit()
        return project_paper

    def get_projects_by_paper_id(
        self, db: Session, *, paper_id: uuid.UUID, user: CurrentUser
    ) -> list[Project]:
        # First, find all project-paper associations for the given paper_id
        project_ids = db.scalars(
            select(ProjectPaper.project_id).where(ProjectPaper.document_id == paper_id)
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
        paper_id: str,
        project_id: str,
        current_user: CurrentUser,
    ) -> Document | None:
        document = self.get_paper_by_project(
            db,
            paper_id=uuid.UUID(paper_id),
            project_id=uuid.UUID(project_id),
            user=current_user,
        )
        if document is None:
            return None
        return paper_crud.add_to_library(
            db,
            document=document,
            user=current_user,
        )


project_paper_crud = ProjectPaperCRUD()
