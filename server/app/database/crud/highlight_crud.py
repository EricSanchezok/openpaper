from typing import Any
from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.models import Document, Highlight, LibraryPaper
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class HighlightBase(BaseModel):
    paper_id: UUID
    raw_text: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    page_number: int | None = None
    role: str | None = None
    type: str | None = None  # HighlightType enum value
    position: dict[str, Any] | None = None  # ScaledPosition JSON
    color: str | None = None  # Highlight color: yellow, green, blue, pink, purple
    zotero_annotation_key: str | None = None


class HighlightCreate(HighlightBase):
    pass


class HighlightUpdate(HighlightBase):
    pass


class HighlightCrud(CRUDBase[Highlight, HighlightCreate, HighlightUpdate]):
    """CRUD operations specifically for Highlight model"""

    def get_highlights_by_paper_id(
        self, db: Session, *, paper_id: str, user: CurrentUser | None = None
    ) -> list[Highlight]:
        """Get highlights associated with document"""
        statement = select(Highlight).where(Highlight.paper_id == paper_id)

        # Add user filter if user is provided
        if user:
            statement = statement.where(Highlight.user_id == user.id)

        return list(db.scalars(statement.order_by(Highlight.created_at)).all())

    def get_zotero_annotation_keys_for_paper(
        self, db: Session, *, paper_id: UUID
    ) -> set[str]:
        rows = db.scalars(
            select(Highlight.zotero_annotation_key).where(
                Highlight.paper_id == paper_id,
                Highlight.zotero_annotation_key.isnot(None),
            )
        ).all()
        return {key for key in rows if key}

    def find_backfill_candidate(
        self,
        db: Session,
        *,
        paper_id: UUID,
        raw_text: str,
        page_number: int | None,
    ) -> Highlight | None:
        normalized_text = raw_text.strip()
        statement = select(Highlight).where(
            Highlight.paper_id == paper_id,
            Highlight.zotero_annotation_key.is_(None),
            func.trim(Highlight.raw_text) == normalized_text,
        )
        if page_number is not None:
            statement = statement.where(Highlight.page_number == page_number)

        # Only backfill when the match is unambiguous; fetch one extra row so we
        # can detect (and reject) the multiple-match case without loading them all.
        matches = db.scalars(statement.limit(2)).all()
        if len(matches) == 1:
            return matches[0]
        return None

    def set_zotero_annotation_key(
        self,
        db: Session,
        *,
        highlight: Highlight,
        zotero_annotation_key: str,
    ) -> Highlight:
        highlight.zotero_annotation_key = zotero_annotation_key
        db.add(highlight)
        db.commit()
        db.refresh(highlight)
        return highlight

    def get_public_highlights_data_by_paper_id(
        self, db: Session, *, share_id: str
    ) -> list[Highlight]:
        """Get public highlights associated with document"""
        return list(
            db.scalars(
                select(Highlight)
                .join(Document, Highlight.paper_id == Document.id)
                .join(LibraryPaper, LibraryPaper.document_id == Document.id)
                .where(
                    LibraryPaper.share_id == share_id,
                    LibraryPaper.is_public.is_(True),
                    Highlight.user_id == LibraryPaper.user_id,
                )
                .order_by(Highlight.created_at)
            ).all()
        )


# Create a single instance to use throughout the application
highlight_crud = HighlightCrud(Highlight)
