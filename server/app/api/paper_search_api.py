from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.database import get_db
from app.database.telemetry import track_event
from app.helpers.ai_limits import AILimitExceeded, enforce_rate_limit
from app.helpers.paper_search import (
    OpenAlexFilter,
    OpenAlexCitationGraph,
    OpenAlexResponse,
    construct_citation_graph,
    get_doi,
    get_work_by_doi,
    search_open_alex,
)
from app.repositories.documents import document_repository
from app.errors import AppError
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.shared.application import Actor
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

# API routes for effectively searching and retrieving papers from external sources

paper_search_router = APIRouter()


@paper_search_router.post("/match", response_model=OpenAlexCitationGraph)
async def get_paper_graph(
    request: Request,
    doi: str | None = None,
    document_id: str | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> OpenAlexCitationGraph:
    """
    Get the citation graph for a paper.

    Either doi or document_id must be provided. If document_id is provided,
    the paper's DOI will be used to look up the OpenAlex ID.
    """
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=request.client.host if request.client else "unknown",
            feature="external_search",
        )
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code,
            message="External search rate limit exceeded",
            status_code=429,
        ) from None
    if not doi and not document_id:
        raise AppError(
            code="citation_graph_source_required",
            message="Either doi or document_id must be provided",
            status_code=400,
        )

    paper = None
    if document_id:
        paper = document_repository.find_accessible(
            db, document_id=document_id, user=current_user
        )
        if not paper:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                status_code=404,
            )
        if not doi:
            if paper.doi:
                doi = str(paper.doi)
            else:
                doi = get_doi(str(paper.title))
                if not doi:
                    raise AppError(
                        code="paper_doi_unavailable",
                        message="A DOI could not be determined for this paper",
                        status_code=400,
                    )

    if not doi:
        raise AppError(
            code="paper_doi_unavailable",
            message="A DOI could not be determined for this paper",
            status_code=400,
        )

    work = get_work_by_doi(doi)
    if not work:
        raise AppError(
            code="openalex_paper_not_found",
            message="OpenAlex could not find a paper for this DOI",
            status_code=404,
        )

    if paper and paper.doi != doi:
        document_repository.update_canonical(
            db,
            document=paper,
            update=DocumentUpdate(doi=doi),
        )

    graph = construct_citation_graph(work.id)
    track_event(
        "citation_graph_view",
        user_id=str(current_user.id),
        properties={
            "cited_by_count": graph.cited_by.meta.get("count", 0),
            "cites_count": graph.cites.meta.get("count", 0),
        },
        db=db,
    )
    return graph


@paper_search_router.get("/author", response_model=OpenAlexResponse)
async def get_author_works(
    request: Request,
    author_id: str = Query(min_length=2, max_length=100),
    page: int = Query(default=1, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> OpenAlexResponse:
    """
    Get works by a specific author from OpenAlex.

    Args:
        author_id: The OpenAlex author ID (e.g., "A5023888391" or full URL).
        page: Page number for pagination.
    """
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=request.client.host if request.client else "unknown",
            feature="external_search",
        )
    except AILimitExceeded as exc:
        raise AppError(
            code=exc.code,
            message="External search rate limit exceeded",
            status_code=429,
        ) from None
    author_filter = OpenAlexFilter(authors=[author_id])
    results = search_open_alex(search_term=None, filter=author_filter, page=page)
    track_event(
        "author_works_view",
        user_id=str(current_user.id),
        properties={
            "page": page,
            "results_count": len(results.results),
            "total_count": results.meta.get("count", 0),
        },
        db=db,
    )
    return results
