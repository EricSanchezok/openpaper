from datetime import datetime

from app.database.models import Annotation, Highlight, Paper
from app.schemas.user import CurrentUser
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload


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


def search_knowledge_base(
    db: Session,
    user: CurrentUser,
    query: str,
    limit: int = 50,
    offset: int = 0,
    papers_filter: list[str] | None = None,
) -> SearchResults:
    """
    Search across papers, annotations, and highlights in a user's knowledge base.
    Returns a hierarchical view with matching content organized under paper metadata.

    Args:
        db: Database session
        user: Current authenticated user
        query: Search query string
        limit: Maximum number of papers to return
        offset: Number of papers to skip (for pagination)
        papers_filter: Optional list of paper IDs to filter results

    Returns:
        SearchResults with hierarchical data structure
    """

    # Create case-insensitive search pattern
    search_pattern = f"%{query.lower()}%"

    # Build the main query for papers that match the search criteria
    # We'll search in paper title, abstract, raw_content, and related annotations/highlights
    matching_highlight_papers = select(Highlight.paper_id).where(
        Highlight.user_id == user.id,
        func.lower(Highlight.raw_text).like(search_pattern),
    )
    matching_annotation_papers = select(Annotation.paper_id).where(
        Annotation.user_id == user.id,
        func.lower(Annotation.content).like(search_pattern),
    )
    paper_statement = (
        select(Paper)
        .where(Paper.user_id == user.id)
        .where(
            or_(
                func.lower(Paper.title).like(search_pattern),
                func.lower(Paper.abstract).like(search_pattern),
                func.lower(Paper.raw_content).like(search_pattern),
                # Include papers that have matching highlights
                Paper.id.in_(matching_highlight_papers),
                # Include papers that have matching annotations
                Paper.id.in_(matching_annotation_papers),
            )
        )
        .order_by(Paper.last_accessed_at.desc())
    )
    if papers_filter:
        paper_statement = paper_statement.where(Paper.id.in_(papers_filter))

    # Get total count for pagination
    total_papers = int(
        db.scalar(
            select(func.count()).select_from(paper_statement.order_by(None).subquery())
        )
        or 0
    )

    # Apply pagination
    papers = list(db.scalars(paper_statement.offset(offset).limit(limit)).all())
    paper_ids = [paper.id for paper in papers]

    matching_highlights = (
        list(
            db.scalars(
                select(Highlight)
                .where(
                    Highlight.paper_id.in_(paper_ids),
                    Highlight.user_id == user.id,
                    func.lower(Highlight.raw_text).like(search_pattern),
                )
                .order_by(Highlight.created_at.desc())
            ).all()
        )
        if paper_ids
        else []
    )
    matching_annotations = (
        list(
            db.scalars(
                select(Annotation)
                .options(joinedload(Annotation.highlight))
                .where(
                    Annotation.paper_id.in_(paper_ids),
                    Annotation.user_id == user.id,
                    func.lower(Annotation.content).like(search_pattern),
                )
                .order_by(Annotation.created_at.desc())
            )
            .unique()
            .all()
        )
        if paper_ids
        else []
    )
    highlights_by_paper: dict[object, list[Highlight]] = {}
    for highlight in matching_highlights:
        highlights_by_paper.setdefault(highlight.paper_id, []).append(highlight)
    annotations_by_paper: dict[object, list[Annotation]] = {}
    for annotation in matching_annotations:
        annotations_by_paper.setdefault(annotation.paper_id, []).append(annotation)

    # For each paper, get matching highlights and annotations
    results = []
    total_highlights = 0
    total_annotations = 0

    for paper in papers:
        paper_highlights = highlights_by_paper.get(paper.id, [])
        paper_annotations = annotations_by_paper.get(paper.id, [])

        # Convert to Pydantic models
        highlight_results = [
            HighlightResult(
                id=str(h.id),
                raw_text=h.raw_text,
                start_offset=h.start_offset,
                end_offset=h.end_offset,
                page_number=h.page_number,
                role=h.role,
                created_at=h.created_at,
            )
            for h in paper_highlights
        ]

        annotation_results = [
            AnnotationResult(
                id=str(a.id),
                content=a.content,
                role=a.role,
                created_at=a.created_at,
                highlight=HighlightResult(
                    id=str(a.highlight.id),
                    raw_text=a.highlight.raw_text,
                    start_offset=a.highlight.start_offset,
                    end_offset=a.highlight.end_offset,
                    page_number=a.highlight.page_number,
                    role=a.highlight.role,
                    created_at=a.highlight.created_at,
                ),
            )
            for a in paper_annotations
        ]

        paper_result = PaperResult(
            id=str(paper.id),
            title=paper.title,
            authors=paper.authors,
            abstract=paper.abstract,
            status=paper.status,
            publish_date=paper.publish_date,
            created_at=paper.created_at,
            last_accessed_at=paper.last_accessed_at,
            highlights=highlight_results,
            annotations=annotation_results,
            preview_url=paper.preview_url,
        )

        results.append(paper_result)
        total_highlights += len(highlight_results)
        total_annotations += len(annotation_results)

    return SearchResults(
        papers=results,
        total_papers=total_papers,
        total_highlights=total_highlights,
        total_annotations=total_annotations,
    )
