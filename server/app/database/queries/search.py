"""Library search over canonical documents and visible research threads."""

from datetime import datetime

from app.database.models import (
    AnnotationComment,
    Document,
    HighlightThread,
    LibraryPaper,
    ResearchItem,
    ResearchScopeType,
)
from app.helpers.s3 import s3_service
from app.schemas.user import CurrentUser
from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session


class HighlightResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    raw_text: str
    start_offset: int | None
    end_offset: int | None
    page_number: int | None
    role: str
    created_at: datetime


class AnnotationResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    role: str
    created_at: datetime
    highlight: HighlightResult


class PaperResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    authors: list[str] | None
    abstract: str | None
    status: str
    publish_date: datetime | None
    created_at: datetime
    last_accessed_at: datetime
    highlights: list[HighlightResult]
    annotations: list[AnnotationResult]
    preview_url: str | None = None


class SearchResults(BaseModel):
    papers: list[PaperResult]
    total_papers: int
    total_highlights: int
    total_annotations: int


class SearchStats(BaseModel):
    total_papers: int
    total_highlights: int
    total_annotations: int
    searchable_items: int


def _visible_research(user_id: int) -> ColumnElement[bool]:
    return or_(
        ResearchItem.is_shared.is_(True),
        ResearchItem.created_by_id == user_id,
    )


def search_knowledge_base(
    db: Session,
    user: CurrentUser,
    query: str,
    limit: int = 50,
    offset: int = 0,
) -> SearchResults:
    search_pattern = f"%{query.lower()}%"
    matching_highlight_documents = (
        select(ResearchItem.document_id)
        .join(
            HighlightThread,
            HighlightThread.research_item_id == ResearchItem.id,
        )
        .where(
            ResearchItem.scope_type == ResearchScopeType.DOCUMENT.value,
            _visible_research(user.id),
            func.lower(HighlightThread.quote_text).like(search_pattern),
        )
    )
    matching_comment_documents = (
        select(ResearchItem.document_id)
        .join(
            AnnotationComment,
            AnnotationComment.thread_id == ResearchItem.id,
        )
        .where(
            ResearchItem.scope_type == ResearchScopeType.DOCUMENT.value,
            _visible_research(user.id),
            func.lower(AnnotationComment.content).like(search_pattern),
        )
    )
    paper_statement = (
        select(Document)
        .join(LibraryPaper, LibraryPaper.document_id == Document.id)
        .where(
            LibraryPaper.user_id == user.id,
            or_(
                func.lower(Document.title).like(search_pattern),
                func.lower(Document.abstract).like(search_pattern),
                func.lower(Document.raw_content).like(search_pattern),
                Document.id.in_(matching_highlight_documents),
                Document.id.in_(matching_comment_documents),
            ),
        )
        .order_by(LibraryPaper.last_accessed_at.desc())
    )
    total_papers = int(
        db.scalar(
            select(func.count()).select_from(paper_statement.order_by(None).subquery())
        )
        or 0
    )
    papers = list(db.scalars(paper_statement.offset(offset).limit(limit)).all())
    paper_ids = [paper.id for paper in papers]
    library_by_document = {
        entry.document_id: entry
        for entry in db.scalars(
            select(LibraryPaper).where(
                LibraryPaper.user_id == user.id,
                LibraryPaper.document_id.in_(paper_ids),
            )
        ).all()
    }

    highlight_rows = (
        db.execute(
            select(ResearchItem, HighlightThread)
            .join(
                HighlightThread,
                HighlightThread.research_item_id == ResearchItem.id,
            )
            .where(
                ResearchItem.document_id.in_(paper_ids),
                _visible_research(user.id),
                func.lower(HighlightThread.quote_text).like(search_pattern),
            )
            .order_by(ResearchItem.created_at.desc())
        ).all()
        if paper_ids
        else []
    )
    comment_rows = (
        db.execute(
            select(ResearchItem, HighlightThread, AnnotationComment)
            .join(
                HighlightThread,
                HighlightThread.research_item_id == ResearchItem.id,
            )
            .join(
                AnnotationComment,
                AnnotationComment.thread_id == ResearchItem.id,
            )
            .where(
                ResearchItem.document_id.in_(paper_ids),
                _visible_research(user.id),
                func.lower(AnnotationComment.content).like(search_pattern),
            )
            .order_by(AnnotationComment.created_at.desc())
        ).all()
        if paper_ids
        else []
    )

    highlights_by_document: dict[
        object, list[tuple[ResearchItem, HighlightThread]]
    ] = {}
    for item, thread in highlight_rows:
        highlights_by_document.setdefault(item.document_id, []).append((item, thread))
    comments_by_document: dict[
        object,
        list[tuple[ResearchItem, HighlightThread, AnnotationComment]],
    ] = {}
    for item, thread, comment in comment_rows:
        comments_by_document.setdefault(item.document_id, []).append(
            (item, thread, comment)
        )

    results: list[PaperResult] = []
    total_highlights = 0
    total_annotations = 0
    for paper in papers:
        highlight_results = [
            HighlightResult(
                id=str(item.id),
                raw_text=thread.quote_text,
                start_offset=thread.start_offset,
                end_offset=thread.end_offset,
                page_number=thread.page_number,
                role=thread.role,
                created_at=item.created_at,
            )
            for item, thread in highlights_by_document.get(paper.id, [])
        ]
        annotation_results = [
            AnnotationResult(
                id=str(comment.id),
                content=comment.content,
                role=comment.role,
                created_at=comment.created_at,
                highlight=HighlightResult(
                    id=str(item.id),
                    raw_text=thread.quote_text,
                    start_offset=thread.start_offset,
                    end_offset=thread.end_offset,
                    page_number=thread.page_number,
                    role=thread.role,
                    created_at=item.created_at,
                ),
            )
            for item, thread, comment in comments_by_document.get(paper.id, [])
        ]
        library_paper = library_by_document[paper.id]
        results.append(
            PaperResult(
                id=str(paper.id),
                title=paper.title,
                authors=paper.authors,
                abstract=paper.abstract,
                status=library_paper.status,
                publish_date=paper.publish_date,
                created_at=paper.created_at,
                last_accessed_at=library_paper.last_accessed_at,
                highlights=highlight_results,
                annotations=annotation_results,
                preview_url=(
                    s3_service.generate_presigned_url(paper.preview_s3_key)
                    if paper.preview_s3_key
                    else None
                ),
            )
        )
        total_highlights += len(highlight_results)
        total_annotations += len(annotation_results)

    return SearchResults(
        papers=results,
        total_papers=total_papers,
        total_highlights=total_highlights,
        total_annotations=total_annotations,
    )
