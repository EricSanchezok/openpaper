"""HTTP adapter for the independent Research search capability."""

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.research.application.search import (
    ResearchSearchRequest,
    ResearchSearchResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends

research_search_router = APIRouter()


@research_search_router.post("", response_model=ResearchSearchResponse)
def search_research(
    payload: ResearchSearchRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    actor: Actor = Depends(get_required_user),
) -> ResearchSearchResponse:
    return executor.query(
        lambda capabilities: capabilities.research_search(
            actor=actor,
            request=payload,
        )
    )
