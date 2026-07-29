from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.billing.application.contracts import (
    IntervalChangeResponse,
    SubscriptionInterval,
)
from app.shared.application import Actor, ApplicationExecutor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends

router = APIRouter()


@router.patch("/subscription/interval", response_model=IntervalChangeResponse)
def change_subscription_interval(
    new_interval: SubscriptionInterval,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> IntervalChangeResponse:
    return executor.command(
        lambda capabilities: capabilities.billing.schedule_interval_change(
            current_user,
            new_interval,
        )
    )


@router.delete("/subscription/interval", response_model=IntervalChangeResponse)
def cancel_scheduled_change(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> IntervalChangeResponse:
    return executor.command(
        lambda capabilities: capabilities.billing.cancel_interval_change(current_user)
    )
