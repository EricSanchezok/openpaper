from app.bootstrap.container import build_billing
from app.database.database import get_db
from app.modules.billing.application.contracts import (
    SubscriptionResponse,
    UsageResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/subscription", response_model=SubscriptionResponse)
def get_user_subscription(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> SubscriptionResponse:
    return build_billing(db=db).get_subscription(current_user)


@router.get("/usage", response_model=UsageResponse)
def get_user_usage(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> UsageResponse:
    return build_billing(db=db).get_usage(current_user)
