"""HTTP adapter for external scholarly discovery."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.papers.application.contracts.discovery import (
    DiscoveryPaperListResponse,
    OpenAlexCitationGraph,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Query, Request

paper_search_router = APIRouter()
author_discovery_router = APIRouter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@paper_search_router.get("/search", response_model=DiscoveryPaperListResponse)
async def search_external_papers(
    request: Request,
    query: str = Query(min_length=2, max_length=500),
    cursor: str | None = Query(default=None, max_length=2048),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> DiscoveryPaperListResponse:
    return await executor.command_async(
        lambda capabilities: capabilities.paper_discovery.search(
            actor=current_user,
            client_ip=_client_ip(request),
            query=query,
            cursor=cursor,
        )
    )


@paper_search_router.post("/match", response_model=OpenAlexCitationGraph)
async def get_paper_graph(
    request: Request,
    doi: str | None = None,
    document_id: UUID | None = None,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> OpenAlexCitationGraph:
    preparation = executor.query(
        lambda capabilities: capabilities.paper_discovery.prepare_match(
            actor=current_user,
            doi=doi,
            document_id=document_id,
        )
    )
    discovery = executor.query(lambda capabilities: capabilities.paper_discovery)
    result = await discovery.fetch_match(
        actor=current_user,
        client_ip=_client_ip(request),
        preparation=preparation,
    )
    return executor.command(
        lambda capabilities: capabilities.paper_discovery.complete_match(
            actor=current_user,
            preparation=preparation,
            result=result,
        )
    )


@author_discovery_router.get("/authors", response_model=DiscoveryPaperListResponse)
async def get_author_works(
    request: Request,
    author_id: str = Query(min_length=2, max_length=100),
    cursor: str | None = Query(default=None, max_length=2048),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> DiscoveryPaperListResponse:
    return await executor.command_async(
        lambda capabilities: capabilities.paper_discovery.author_works(
            actor=current_user,
            client_ip=_client_ip(request),
            author_id=author_id,
            cursor=cursor,
        )
    )
