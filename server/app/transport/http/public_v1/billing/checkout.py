from app.bootstrap.container import build_billing
from app.database.database import get_db
from app.modules.billing.application.contracts import (
    CheckoutSessionResponse,
    CheckoutSessionStatusResponse,
    SubscriptionInterval,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

router = APIRouter()


@router.post(
    "/checkout-sessions",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_checkout_session(
    interval: SubscriptionInterval,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CheckoutSessionResponse:
    return build_billing(db=db).create_checkout(current_user, interval)


@router.get(
    "/checkout-sessions/{session_id}",
    response_model=CheckoutSessionStatusResponse,
)
def session_status(
    session_id: str,
    db: Session = Depends(get_db),
) -> CheckoutSessionStatusResponse:
    return build_billing(db=db).checkout_status(session_id)
