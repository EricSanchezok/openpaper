from app.auth.dependencies import get_required_user
from app.database.database import get_db
from app.database.models import (
    AnnotationComment,
    LibraryPaper,
    ResearchItem,
    ResearchItemKind,
)
from app.database.queries.search import (
    SearchResults,
    SearchStats,
    search_knowledge_base,
)
from app.database.telemetry import track_event
from app.errors import AppError
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# API router for knowledge base search functionality
search_router = APIRouter()


@search_router.get("/")
async def search_knowledge_base_endpoint(
    q: str = Query(
        ...,
        min_length=2,
        max_length=1_000,
        description="Search query string",
    ),
    limit: int = Query(
        50, ge=1, le=100, description="Maximum number of papers to return"
    ),
    offset: int = Query(0, ge=0, description="Number of papers to skip for pagination"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> SearchResults:
    """
    Search across papers, annotations, and highlights in the user's knowledge base.

    Returns a hierarchical view with matching content organized under paper metadata.
    The search looks through:
    - Document titles, abstracts, and raw content
    - Highlight thread text
    - Annotation comment content

    Results are organized by paper, with matching highlights and annotations
    sub-referenced under each paper's metadata.
    """
    query = q.strip()
    if len(query) < 2:
        raise AppError(
            code="search_query_invalid",
            message="Search query must contain at least 2 characters",
            status_code=422,
        )

    results = search_knowledge_base(
        db=db,
        user=current_user,
        query=query,
        limit=limit,
        offset=offset,
    )
    track_event(
        "knowledge_base_search",
        user_id=str(current_user.id),
        properties={
            "query": query,
            "total_papers": results.total_papers,
            "total_highlights": results.total_highlights,
            "total_annotations": results.total_annotations,
            "limit": limit,
            "offset": offset,
        },
        db=db,
    )
    return results


@search_router.get("/stats", response_model=SearchStats)
async def get_search_stats(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> SearchStats:
    """
    Get statistics about the user's knowledge base for search context.

    Returns counts of papers, highlights, and annotations.
    """
    total_papers = int(
        db.scalar(
            select(func.count(LibraryPaper.id)).where(
                LibraryPaper.user_id == current_user.id
            )
        )
        or 0
    )
    total_highlights = int(
        db.scalar(
            select(func.count(ResearchItem.id)).where(
                ResearchItem.created_by_id == current_user.id,
                ResearchItem.kind == ResearchItemKind.HIGHLIGHT_THREAD.value,
            )
        )
        or 0
    )
    total_annotations = int(
        db.scalar(
            select(func.count(AnnotationComment.id)).where(
                AnnotationComment.created_by_id == current_user.id
            )
        )
        or 0
    )
    return SearchStats(
        total_papers=total_papers,
        total_highlights=total_highlights,
        total_annotations=total_annotations,
        searchable_items=total_papers + total_highlights + total_annotations,
    )
