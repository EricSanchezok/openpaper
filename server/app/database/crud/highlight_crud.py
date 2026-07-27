from typing import Any
from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.models import Document, Highlight, LibraryPaper
from app.policies.documents import require_document_access
from app.policies.research import (
    can_view_research_item,
    require_project_research_access,
    require_research_item_manager,
)
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
    project_id: UUID | None = None
    is_shared: bool = False


class HighlightCreate(HighlightBase):
    pass


class HighlightUpdate(HighlightBase):
    pass


class HighlightCrud(CRUDBase[Highlight, HighlightCreate, HighlightUpdate]):
    """CRUD operations specifically for Highlight model"""

    def get_highlights_by_paper_id(
        self,
        db: Session,
        *,
        paper_id: UUID,
        user: CurrentUser,
        project_id: UUID | None = None,
    ) -> list[Highlight]:
        """Return private highlights or the visible research layer of a Project."""
        require_document_access(
            db,
            document_id=paper_id,
            user_id=user.id,
            project_id=project_id,
        )
        statement = select(Highlight).where(Highlight.paper_id == paper_id)
        if project_id is None:
            statement = statement.where(
                Highlight.project_id.is_(None),
                Highlight.user_id == user.id,
            )
        else:
            access = require_project_research_access(
                db,
                project_id=project_id,
                user_id=user.id,
            )
            statement = statement.where(
                Highlight.project_id == project_id,
                (Highlight.is_shared.is_(True)) | (Highlight.user_id == access.user_id),
            )

        return list(db.scalars(statement.order_by(Highlight.created_at)).all())

    def create_scoped(
        self,
        db: Session,
        *,
        obj_in: HighlightCreate,
        user: CurrentUser,
    ) -> Highlight | None:
        require_document_access(
            db,
            document_id=obj_in.paper_id,
            user_id=user.id,
            project_id=obj_in.project_id,
        )
        if obj_in.project_id is not None:
            require_project_research_access(
                db,
                project_id=obj_in.project_id,
                user_id=user.id,
            )
        return self.create(db, obj_in=obj_in, user=user)

    def get_for_mutation(
        self,
        db: Session,
        *,
        highlight_id: UUID,
        user: CurrentUser,
    ) -> Highlight | None:
        highlight = db.get(Highlight, highlight_id)
        if highlight is None:
            return None
        if highlight.project_id is None:
            return highlight if highlight.user_id == user.id else None
        access = require_project_research_access(
            db,
            project_id=highlight.project_id,
            user_id=user.id,
        )
        require_research_item_manager(
            access=access,
            created_by_id=highlight.user_id,
        )
        return highlight

    def can_view(
        self,
        db: Session,
        *,
        highlight: Highlight,
        user: CurrentUser,
    ) -> bool:
        if highlight.project_id is None:
            return highlight.user_id == user.id
        access = require_project_research_access(
            db,
            project_id=highlight.project_id,
            user_id=user.id,
        )
        return can_view_research_item(
            access=access,
            created_by_id=highlight.user_id,
            is_shared=highlight.is_shared,
        )

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
                    Highlight.project_id.is_(None),
                )
                .order_by(Highlight.created_at)
            ).all()
        )


# Create a single instance to use throughout the application
highlight_crud = HighlightCrud(Highlight)
