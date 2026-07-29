"""HTTP adapter for external scholarly discovery."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_paper_discovery
from app.database.database import get_db
from app.modules.papers.application.contracts.discovery import (
    OpenAlexCitationGraph,
    OpenAlexResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

paper_search_router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@paper_search_router.get("/search", response_model=OpenAlexResponse)
async def search_external_papers(
    request: Request,
    query: str = Query(min_length=2, max_length=500),
    page: int = Query(default=1, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> OpenAlexResponse:
    return await build_paper_discovery(db=db).search(
        actor=current_user,
        client_ip=_client_ip(request),
        query=query,
        page=page,
    )


@paper_search_router.post("/match", response_model=OpenAlexCitationGraph)
async def get_paper_graph(
    request: Request,
    doi: str | None = None,
    document_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> OpenAlexCitationGraph:
    return await build_paper_discovery(db=db).match(
        actor=current_user,
        client_ip=_client_ip(request),
        doi=doi,
        document_id=document_id,
    )


@paper_search_router.get("/authors", response_model=OpenAlexResponse)
async def get_author_works(
    request: Request,
    author_id: str = Query(min_length=2, max_length=100),
    page: int = Query(default=1, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> OpenAlexResponse:
    return await build_paper_discovery(db=db).author_works(
        actor=current_user,
        client_ip=_client_ip(request),
        author_id=author_id,
        page=page,
    )
