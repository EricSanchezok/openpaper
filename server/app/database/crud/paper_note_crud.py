from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.models import PaperNote
from app.policies.documents import require_document_access
from app.policies.research import (
    require_project_research_access,
    require_research_item_manager,
)
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class PaperNoteBase(BaseModel):
    paper_id: UUID
    content: str
    project_id: UUID | None = None
    is_shared: bool = False


class PaperNoteCreate(PaperNoteBase):
    pass


class PaperNoteUpdate(BaseModel):
    content: str


class PaperNoteCRUD(CRUDBase[PaperNote, PaperNoteCreate, PaperNoteUpdate]):
    """CRUD operations specifically for PaperNote model"""

    def get_paper_note_by_paper_id(
        self,
        db: Session,
        *,
        paper_id: str,
        user: CurrentUser,
        project_id: UUID | None = None,
    ) -> PaperNote | None:
        document_id = UUID(str(paper_id))
        require_document_access(
            db,
            document_id=document_id,
            user_id=user.id,
            project_id=project_id,
        )
        statement = select(PaperNote).where(PaperNote.paper_id == document_id)
        if project_id is None:
            statement = statement.where(
                PaperNote.project_id.is_(None),
                PaperNote.user_id == user.id,
            )
        else:
            require_project_research_access(
                db,
                project_id=project_id,
                user_id=user.id,
            )
            statement = statement.where(
                PaperNote.project_id == project_id,
                (PaperNote.is_shared.is_(True)) | (PaperNote.user_id == user.id),
            )
        return db.scalar(
            statement.order_by(
                (PaperNote.user_id == user.id).desc(),
                PaperNote.updated_at.desc(),
            )
        )

    def create_scoped(
        self,
        db: Session,
        *,
        obj_in: PaperNoteCreate,
        user: CurrentUser,
    ) -> PaperNote | None:
        require_document_access(
            db,
            document_id=obj_in.paper_id,
            user_id=user.id,
            project_id=obj_in.project_id,
        )
        return self.create(db, obj_in=obj_in, user=user)

    def get_for_mutation(
        self,
        db: Session,
        *,
        note_id: UUID,
        user: CurrentUser,
    ) -> PaperNote | None:
        note = db.get(PaperNote, note_id)
        if note is None:
            return None
        if note.project_id is None:
            return note if note.user_id == user.id else None
        access = require_project_research_access(
            db,
            project_id=note.project_id,
            user_id=user.id,
        )
        require_research_item_manager(
            access=access,
            created_by_id=note.user_id,
        )
        return note


# Create a single instance to use throughout the application
paper_note_crud = PaperNoteCRUD(PaperNote)
