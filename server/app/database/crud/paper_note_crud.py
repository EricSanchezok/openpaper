from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.models import PaperNote
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class PaperNoteBase(BaseModel):
    paper_id: UUID
    content: str | None = None


class PaperNoteCreate(PaperNoteBase):
    pass


class PaperNoteUpdate(BaseModel):
    content: str


class PaperNoteCRUD(CRUDBase[PaperNote, PaperNoteCreate, PaperNoteUpdate]):
    """CRUD operations specifically for PaperNote model"""

    def get_paper_note_by_paper_id(
        self, db: Session, *, paper_id: str, user: CurrentUser
    ) -> PaperNote | None:
        """Get paper note associated with document"""

        return db.scalars(
            select(PaperNote)
            .where(PaperNote.paper_id == paper_id, PaperNote.user_id == user.id)
            .order_by(PaperNote.created_at)
        ).first()


# Create a single instance to use throughout the application
paper_note_crud = PaperNoteCRUD(PaperNote)
