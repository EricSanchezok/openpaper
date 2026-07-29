from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.billing.application.contracts import (
    PortalSessionResponse,
    SubscriptionActionResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, status

router = APIRouter()


@router.post(
    "/portal-sessions",
    response_model=PortalSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_portal_session(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> PortalSessionResponse:
    return executor.command(
        lambda capabilities: capabilities.billing.create_portal(current_user)
    )


@router.post("/subscription/resume", response_model=SubscriptionActionResponse)
def resume_subscription(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> SubscriptionActionResponse:
    return executor.command(
        lambda capabilities: capabilities.billing.resume(current_user)
    )
