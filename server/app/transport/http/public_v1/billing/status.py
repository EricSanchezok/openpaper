from app.bootstrap.workflows.billing import BillingWorkflow
from app.modules.billing.application.contracts import (
    SubscriptionResponse,
    UsageResponse,
)
from app.shared.application import Actor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from app.transport.http.public_v1.billing.dependencies import get_billing_workflow
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/subscription", response_model=SubscriptionResponse)
def get_user_subscription(
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> SubscriptionResponse:
    return workflow.get_subscription(
        actor=current_user,
        operation=operation,
    )


@router.get("/usage", response_model=UsageResponse)
def get_user_usage(
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
) -> UsageResponse:
    return workflow.get_usage(current_user)
