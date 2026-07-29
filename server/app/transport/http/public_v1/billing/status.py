from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.billing.application.contracts import (
    SubscriptionResponse,
    UsageResponse,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/subscription", response_model=SubscriptionResponse)
def get_user_subscription(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> SubscriptionResponse:
    return executor.query(
        lambda capabilities: capabilities.billing.get_subscription(current_user)
    )


@router.get("/usage", response_model=UsageResponse)
def get_user_usage(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> UsageResponse:
    return executor.query(
        lambda capabilities: capabilities.billing.get_usage(current_user)
    )
