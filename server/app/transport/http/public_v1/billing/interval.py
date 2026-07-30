from app.bootstrap.workflows.billing import BillingWorkflow
from app.modules.billing.application.contracts import (
    IntervalChangeResponse,
    SubscriptionInterval,
)
from app.shared.application import Actor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from app.transport.http.public_v1.billing.dependencies import get_billing_workflow
from fastapi import APIRouter, Depends

router = APIRouter()


@router.patch("/subscription/interval", response_model=IntervalChangeResponse)
def change_subscription_interval(
    new_interval: SubscriptionInterval,
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> IntervalChangeResponse:
    return workflow.schedule_interval_change(
        actor=current_user,
        operation=operation,
        new_interval=new_interval,
    )


@router.delete("/subscription/interval", response_model=IntervalChangeResponse)
def cancel_scheduled_change(
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> IntervalChangeResponse:
    return workflow.cancel_interval_change(
        actor=current_user,
        operation=operation,
    )
