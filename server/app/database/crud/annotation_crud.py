from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.crud.highlight_crud import highlight_crud
from app.database.models import Annotation, Document, Highlight, LibraryPaper
from app.policies.research import (
    require_project_research_access,
    require_research_item_manager,
)
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class AnnotationBase(BaseModel):
    paper_id: UUID
    highlight_id: UUID
    content: str | None = None
    role: str | None = None


class AnnotationCreate(AnnotationBase):
    pass


class AnnotationUpdate(AnnotationBase):
    pass


class AnnotationCrud(CRUDBase[Annotation, AnnotationCreate, AnnotationUpdate]):
    """CRUD operations specifically for Annotation model"""

    def get_annotations_by_paper_id(
        self,
        db: Session,
        *,
        paper_id: UUID,
        user: CurrentUser,
        project_id: UUID | None = None,
    ) -> list[Annotation]:
        visible_highlights = highlight_crud.get_highlights_by_paper_id(
            db,
            paper_id=paper_id,
            user=user,
            project_id=project_id,
        )
        highlight_ids = [highlight.id for highlight in visible_highlights]
        if not highlight_ids:
            return []
        return list(
            db.scalars(
                select(Annotation)
                .where(Annotation.highlight_id.in_(highlight_ids))
                .order_by(Annotation.created_at)
            ).all()
        )

    def create_for_highlight(
        self,
        db: Session,
        *,
        obj_in: AnnotationCreate,
        user: CurrentUser,
    ) -> Annotation | None:
        highlight = db.get(Highlight, obj_in.highlight_id)
        if (
            highlight is None
            or highlight.paper_id != obj_in.paper_id
            or not highlight_crud.can_view(db, highlight=highlight, user=user)
        ):
            return None
        return self.create(db, obj_in=obj_in, user=user)

    def get_for_mutation(
        self,
        db: Session,
        *,
        annotation_id: UUID,
        user: CurrentUser,
    ) -> Annotation | None:
        annotation = db.get(Annotation, annotation_id)
        if annotation is None:
            return None
        highlight = db.get(Highlight, annotation.highlight_id)
        if highlight is None:
            return None
        if highlight.project_id is None:
            return annotation if annotation.user_id == user.id else None
        access = require_project_research_access(
            db,
            project_id=highlight.project_id,
            user_id=user.id,
        )
        require_research_item_manager(
            access=access,
            created_by_id=annotation.user_id,
        )
        return annotation

    def get_public_annotations_data_by_paper_id(
        self,
        db: Session,
        *,
        share_id: UUID,
    ) -> list[Annotation]:
        """Get public annotations associated with document"""

        return list(
            db.scalars(
                select(Annotation)
                .join(Document, Annotation.paper_id == Document.id)
                .join(LibraryPaper, LibraryPaper.document_id == Document.id)
                .join(Highlight, Annotation.highlight_id == Highlight.id)
                .where(
                    LibraryPaper.share_id == str(share_id),
                    LibraryPaper.is_public.is_(True),
                    Annotation.user_id == LibraryPaper.user_id,
                    Highlight.project_id.is_(None),
                )
                .order_by(Annotation.created_at)
            ).all()
        )


# Create a single instance to use throughout the application
annotation_crud = AnnotationCrud(Annotation)
