"""HTTP adapter for external scholarly discovery."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.execution import get_paper_discovery_workflow
from app.bootstrap.workflows.discovery import PaperDiscoveryWorkflow
from app.modules.papers.application.contracts.discovery import (
    DiscoveryPaperListResponse,
    OpenAlexCitationGraph,
)
from app.shared.application import Actor, OperationContext
from app.transport.client_ip import http_client_ip
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Query, Request

paper_search_router = APIRouter()
author_discovery_router = APIRouter()


@paper_search_router.get("/search", response_model=DiscoveryPaperListResponse)
async def search_external_papers(
    request: Request,
    query: str = Query(min_length=2, max_length=500),
    cursor: str | None = Query(default=None, max_length=2048),
    workflow: PaperDiscoveryWorkflow = Depends(get_paper_discovery_workflow),
    current_user: Actor = Depends(get_required_user),
) -> DiscoveryPaperListResponse:
    return await workflow.search(
        actor=current_user,
        client_ip=http_client_ip(request),
        query=query,
        cursor=cursor,
    )


@paper_search_router.post("/match", response_model=OpenAlexCitationGraph)
async def get_paper_graph(
    request: Request,
    doi: str | None = None,
    document_id: UUID | None = None,
    workflow: PaperDiscoveryWorkflow = Depends(get_paper_discovery_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> OpenAlexCitationGraph:
    return await workflow.match(
        actor=current_user,
        operation=operation,
        client_ip=http_client_ip(request),
        doi=doi,
        document_id=document_id,
    )


@author_discovery_router.get("/authors", response_model=DiscoveryPaperListResponse)
async def get_author_works(
    request: Request,
    author_id: str = Query(min_length=2, max_length=100),
    cursor: str | None = Query(default=None, max_length=2048),
    workflow: PaperDiscoveryWorkflow = Depends(get_paper_discovery_workflow),
    current_user: Actor = Depends(get_required_user),
) -> DiscoveryPaperListResponse:
    return await workflow.author_works(
        actor=current_user,
        client_ip=http_client_ip(request),
        author_id=author_id,
        cursor=cursor,
    )
