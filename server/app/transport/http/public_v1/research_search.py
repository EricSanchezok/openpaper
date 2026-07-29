"""HTTP adapter for the independent Research search capability."""

from app.bootstrap.settings import AppSettings
from app.bootstrap.container import build_research_search
from app.database.database import get_db
from app.modules.research.application.search import (
    ResearchSearchRequest,
    ResearchSearchResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

research_search_router = APIRouter()


@research_search_router.post("", response_model=ResearchSearchResponse)
def search_research(
    payload: ResearchSearchRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_required_user),
) -> ResearchSearchResponse:
    settings: AppSettings = request.app.state.settings
    return build_research_search(
        db=db,
        cursor_secret=settings.paper_search_cursor_secret,
    )(actor=actor, request=payload)
