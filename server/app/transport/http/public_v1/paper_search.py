from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.database.telemetry import track_event
from app.modules.papers.application.contracts.search import (
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchStats,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Request

# API router for knowledge base search functionality
search_router = APIRouter()


@search_router.post("", response_model=PaperSearchResponse)
async def search_papers_endpoint(
    request: PaperSearchRequest,
    http_request: Request,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
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
    results = executor.query(
        lambda capabilities: capabilities.paper_search(
            actor=current_user,
            request=request,
        )
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
    )
    return results


@search_router.get("/stats", response_model=PaperSearchStats)
async def get_search_stats(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> PaperSearchStats:
    """
    Get statistics about the user's knowledge base for search context.

    Returns counts of papers, highlights, and annotations.
    """
    return executor.query(
        lambda capabilities: capabilities.paper_search_stats(actor=current_user)
    )
