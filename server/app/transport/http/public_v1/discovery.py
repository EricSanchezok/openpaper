"""HTTP adapter for external scholarly discovery."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import build_paper_discovery
from app.database.database import get_db
from app.modules.papers.application.contracts.discovery import (
    DiscoveryPaperListResponse,
    OpenAlexCitationGraph,
)
from app.modules.papers.application.discovery import DiscoverPapers
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

paper_search_router = APIRouter()
author_discovery_router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _discovery(request: Request, db: Session) -> DiscoverPapers:
    return build_paper_discovery(
        db=db,
        cursor_secret=request.app.state.settings.paper_search_cursor_secret,
    )


@paper_search_router.get("/search", response_model=DiscoveryPaperListResponse)
async def search_external_papers(
    request: Request,
    query: str = Query(min_length=2, max_length=500),
    cursor: str | None = Query(default=None, max_length=2048),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DiscoveryPaperListResponse:
    return await _discovery(request, db).search(
        actor=current_user,
        client_ip=_client_ip(request),
        query=query,
        cursor=cursor,
    )


@paper_search_router.post("/match", response_model=OpenAlexCitationGraph)
async def get_paper_graph(
    request: Request,
    doi: str | None = None,
    document_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> OpenAlexCitationGraph:
    return await _discovery(request, db).match(
        actor=current_user,
        client_ip=_client_ip(request),
        doi=doi,
        document_id=document_id,
    )


@author_discovery_router.get(
    "/authors", response_model=DiscoveryPaperListResponse
)
async def get_author_works(
    request: Request,
    author_id: str = Query(min_length=2, max_length=100),
    cursor: str | None = Query(default=None, max_length=2048),
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DiscoveryPaperListResponse:
    return await _discovery(request, db).author_works(
        actor=current_user,
        client_ip=_client_ip(request),
        author_id=author_id,
        cursor=cursor,
    )
