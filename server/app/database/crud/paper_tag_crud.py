import uuid

from app.database.crud.base_crud import CRUDBase
from app.database.models import (
    Document,
    LibraryPaper,
    LibraryPaperTag,
    PaperTag,
)
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload


# Pydantic models for PaperTag
class PaperTagBase(BaseModel):
    name: str
    color: str | None = None


class PaperTagCreate(PaperTagBase):
    pass


class PaperTagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None


class PaperTagCRUD(CRUDBase[PaperTag, PaperTagCreate, PaperTagUpdate]):
    def create(
        self,
        db: Session,
        *,
        obj_in: PaperTagCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> PaperTag | None:
        if not user:
            raise ValueError("User must be provided to create a paper tag")

        db_obj = PaperTag(
            name=obj_in.name,
            color=obj_in.color,
            user_id=user.id,
        )
        db.add(db_obj)
        if auto_commit:
            db.commit()
            db.refresh(db_obj)
        else:
            db.flush()
        return db_obj

    def get_by_name(
        self, db: Session, *, name: str, user: CurrentUser
    ) -> PaperTag | None:
        return db.scalars(
            select(PaperTag).where(PaperTag.name == name, PaperTag.user_id == user.id)
        ).first()

    def get_or_create_by_name(
        self,
        db: Session,
        *,
        name: str,
        user_id: int,
        commit: bool = True,
    ) -> PaperTag | None:
        """Return the user's tag matching ``name`` (case-insensitive, trimmed),
        creating it with the original casing if none exists.

        Returns ``None`` for blank names. This is the single reuse rule that both
        keyword ingestion (webhook) and the keywords->tags migration rely on, so
        neither produces near-duplicate tags differing only by case or whitespace.
        """
        normalized = (name or "").strip()
        if not normalized:
            return None

        existing = db.scalars(
            select(PaperTag).where(
                PaperTag.user_id == user_id,
                func.lower(PaperTag.name) == normalized.lower(),
            )
        ).first()
        if existing:
            return existing

        db_obj = PaperTag(name=normalized, color=None, user_id=user_id)
        db.add(db_obj)
        if commit:
            db.commit()
            db.refresh(db_obj)
        else:
            # Flush so the generated id is available to callers building
            # associations within the same (uncommitted) transaction.
            db.flush()
        return db_obj

    def apply_keyword_tags(
        self,
        db: Session,
        *,
        paper_id: uuid.UUID,
        keywords: list[str],
        user_id: int,
        commit: bool = True,
    ) -> int:
        """Turn a paper's extracted keywords into user tags and attach them.

        For each keyword, reuses an existing tag (case-insensitive) or creates
        one, then links it to the paper if not already linked. Idempotent — safe
        to re-run. Returns the number of new paper<->tag associations created.
        """
        if not keywords:
            return 0

        library_paper = db.scalar(
            select(LibraryPaper).where(
                LibraryPaper.document_id == paper_id,
                LibraryPaper.user_id == user_id,
            )
        )
        if library_paper is None:
            return 0
        existing_tag_ids = set(
            db.scalars(
                select(LibraryPaperTag.tag_id).where(
                    LibraryPaperTag.library_paper_id == library_paper.id
                )
            ).all()
        )

        new_associations = 0
        seen_tag_ids: set[uuid.UUID] = set()
        for keyword in keywords:
            tag = self.get_or_create_by_name(
                db, name=keyword, user_id=user_id, commit=False
            )
            if tag is None or tag.id in seen_tag_ids:
                continue
            seen_tag_ids.add(tag.id)
            if tag.id in existing_tag_ids:
                continue
            db.add(
                LibraryPaperTag(
                    library_paper_id=library_paper.id,
                    tag_id=tag.id,
                )
            )
            new_associations += 1

        if commit:
            db.commit()
        else:
            db.flush()
        return new_associations

    def add_tag_to_paper(
        self, db: Session, *, paper_id: uuid.UUID, tag_id: uuid.UUID, user: CurrentUser
    ) -> LibraryPaperTag | None:
        library_paper = db.scalar(
            select(LibraryPaper).where(
                LibraryPaper.document_id == paper_id,
                LibraryPaper.user_id == user.id,
            )
        )
        if library_paper is None:
            return None

        # Ensure tag belongs to the user
        tag = db.scalars(
            select(PaperTag).where(PaperTag.id == tag_id, PaperTag.user_id == user.id)
        ).first()
        if not tag:
            return None

        association = LibraryPaperTag(
            library_paper_id=library_paper.id,
            tag_id=tag_id,
        )
        db.add(association)
        db.commit()
        return association

    def remove_tag_from_paper(
        self, db: Session, *, paper_id: uuid.UUID, tag_id: uuid.UUID, user: CurrentUser
    ) -> None:
        library_paper = db.scalar(
            select(LibraryPaper).where(
                LibraryPaper.document_id == paper_id,
                LibraryPaper.user_id == user.id,
            )
        )
        if library_paper is None:
            return

        association = db.scalars(
            select(LibraryPaperTag).where(
                LibraryPaperTag.library_paper_id == library_paper.id,
                LibraryPaperTag.tag_id == tag_id,
            )
        ).first()

        if association:
            db.delete(association)
            db.commit()

    def get_tags_for_paper(
        self, db: Session, *, paper_id: uuid.UUID, user: CurrentUser
    ) -> list[PaperTag]:
        library_paper = db.scalar(
            select(LibraryPaper)
            .options(selectinload(LibraryPaper.tags))
            .where(
                LibraryPaper.document_id == paper_id,
                LibraryPaper.user_id == user.id,
            )
        )
        if library_paper is None:
            return []
        return list(library_paper.tags)

    def get_papers_for_tag(
        self, db: Session, *, tag_id: uuid.UUID, user: CurrentUser
    ) -> list[Document]:
        # Ensure tag belongs to the user
        tag = db.scalars(
            select(PaperTag)
            .options(
                selectinload(PaperTag.library_papers).selectinload(
                    LibraryPaper.document
                )
            )
            .where(PaperTag.id == tag_id, PaperTag.user_id == user.id)
        ).first()
        if not tag:
            return []
        return [library_paper.document for library_paper in tag.library_papers]

    def bulk_add_tags_to_papers(
        self,
        db: Session,
        *,
        paper_ids: list[uuid.UUID],
        tag_ids: list[uuid.UUID],
        user: CurrentUser,
    ) -> None:
        # First, verify all papers and tags belong to the user
        library_entries = list(
            db.scalars(
                select(LibraryPaper).where(
                    LibraryPaper.user_id == user.id,
                    LibraryPaper.document_id.in_(paper_ids),
                )
            ).all()
        )
        library_by_document = {entry.document_id: entry for entry in library_entries}
        if len(library_by_document) != len(set(paper_ids)):
            raise ValueError(
                "One or more papers not found or do not belong to the user."
            )

        found_tag_ids = set(
            db.scalars(
                select(PaperTag.id).where(
                    PaperTag.user_id == user.id, PaperTag.id.in_(tag_ids)
                )
            ).all()
        )
        if len(found_tag_ids) != len(set(tag_ids)):
            raise ValueError("One or more tags not found or do not belong to the user.")

        existing_pairs = set(
            db.execute(
                select(
                    LibraryPaperTag.library_paper_id,
                    LibraryPaperTag.tag_id,
                ).where(
                    LibraryPaperTag.library_paper_id.in_(
                        [entry.id for entry in library_entries]
                    ),
                    LibraryPaperTag.tag_id.in_(tag_ids),
                )
            ).tuples()
        )
        associations_to_create: list[LibraryPaperTag] = []
        for paper_id in paper_ids:
            library_paper_id = library_by_document[paper_id].id
            for tag_id in tag_ids:
                if (library_paper_id, tag_id) not in existing_pairs:
                    associations_to_create.append(
                        LibraryPaperTag(
                            library_paper_id=library_paper_id,
                            tag_id=tag_id,
                        )
                    )

        if associations_to_create:
            db.add_all(associations_to_create)
            db.commit()


paper_tag_crud = PaperTagCRUD(PaperTag)
