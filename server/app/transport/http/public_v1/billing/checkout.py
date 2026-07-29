from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.billing.application.contracts import (
    CheckoutSessionResponse,
    CheckoutSessionStatusResponse,
    SubscriptionInterval,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, status

router = APIRouter()


@router.post(
    "/checkout-sessions",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_checkout_session(
    interval: SubscriptionInterval,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> CheckoutSessionResponse:
    return executor.command(
        lambda capabilities: capabilities.billing.create_checkout(
            current_user,
            interval,
        )
    )


@router.get(
    "/checkout-sessions/{session_id}",
    response_model=CheckoutSessionStatusResponse,
)
def session_status(
    session_id: str,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> CheckoutSessionStatusResponse:
    return executor.query(
        lambda capabilities: capabilities.billing.checkout_status(session_id)
    )
