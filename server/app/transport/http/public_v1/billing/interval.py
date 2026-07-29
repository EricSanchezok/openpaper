from app.bootstrap.container import build_billing
from app.database.database import get_db
from app.modules.billing.application.contracts import (
    IntervalChangeResponse,
    SubscriptionInterval,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

router = APIRouter()


@router.patch("/subscription/interval", response_model=IntervalChangeResponse)
def change_subscription_interval(
    new_interval: SubscriptionInterval,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> IntervalChangeResponse:
    return build_billing(db=db).schedule_interval_change(current_user, new_interval)


@router.delete("/subscription/interval", response_model=IntervalChangeResponse)
def cancel_scheduled_change(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> IntervalChangeResponse:
    return build_billing(db=db).cancel_interval_change(current_user)
