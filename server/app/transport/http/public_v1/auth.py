"""HTTP adapters for product-specific identity capabilities."""

from app.bootstrap.container import build_identity, build_paper_topics
from app.database.database import get_db
from app.modules.identity.application.contracts import (
    SetUserBlockedRequest,
    SetUserBlockedResponse,
)
from app.modules.papers.application.topics import TopicListResponse
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import (
    get_admin_user,
    get_required_user,
)
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

auth_router = APIRouter()
admin_router = APIRouter()


@auth_router.get("/topics", response_model=TopicListResponse)
def get_topics(
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> TopicListResponse:
    return build_paper_topics(db=db)(actor=current_user)


@admin_router.put(
    "/users/{user_id}/block",
    response_model=SetUserBlockedResponse,
)
def block_user(
    user_id: int,
    request: SetUserBlockedRequest,
    admin_user: Actor = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> SetUserBlockedResponse:
    return build_identity(db=db).set_blocked(
        actor=admin_user,
        user_id=user_id,
        request=request,
    )
