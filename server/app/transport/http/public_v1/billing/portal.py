from app.bootstrap.container import build_billing
from app.database.database import get_db
from app.modules.billing.application.contracts import (
    PortalSessionResponse,
    SubscriptionActionResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

router = APIRouter()


@router.post(
    "/portal-sessions",
    response_model=PortalSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_portal_session(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> PortalSessionResponse:
    return build_billing(db=db).create_portal(current_user)


@router.post("/subscription/resume", response_model=SubscriptionActionResponse)
def resume_subscription(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> SubscriptionActionResponse:
    return build_billing(db=db).resume(current_user)
