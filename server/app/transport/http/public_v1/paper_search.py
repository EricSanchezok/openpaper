from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.bootstrap.providers import (
    build_paper_search,
    build_project_document_visibility,
)
from app.bootstrap.settings import AppSettings
from app.database.database import get_db
from app.database.telemetry import track_event
from app.modules.papers.application.contracts.search import (
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchStats,
)
from app.modules.papers.application.search import (
    GetPaperSearchStats,
    SearchCursorCodec,
    SearchPapers,
)
from app.shared.application import Actor
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

# API router for knowledge base search functionality
search_router = APIRouter()


@search_router.post("", response_model=PaperSearchResponse)
async def search_knowledge_base_endpoint(
    request: PaperSearchRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> PaperSearchResponse:
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
    settings: AppSettings = http_request.app.state.settings
    results = SearchPapers(
        build_paper_search(backend=settings.paper_search_backend, db=db),
        SearchCursorCodec(settings.paper_search_cursor_secret),
        build_project_document_visibility(db=db),
    )(
        actor=current_user,
        request=request,
    )
    track_event(
        "knowledge_base_search",
        user_id=str(current_user.id),
        properties={
            "query": request.query,
            "total": results.total,
            "limit": request.limit,
            "has_cursor": request.cursor is not None,
        },
        db=db,
    )
    return results


@search_router.get("/stats", response_model=PaperSearchStats)
async def get_search_stats(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> PaperSearchStats:
    """
    Get statistics about the user's knowledge base for search context.

    Returns counts of papers, highlights, and annotations.
    """
    settings: AppSettings = request.app.state.settings
    return GetPaperSearchStats(
        build_paper_search(backend=settings.paper_search_backend, db=db),
        build_project_document_visibility(db=db),
    )(actor=current_user)
