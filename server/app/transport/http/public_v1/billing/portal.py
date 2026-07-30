from app.bootstrap.workflows.billing import BillingWorkflow
from app.modules.billing.application.contracts import (
    PortalSessionResponse,
    SubscriptionActionResponse,
)
from app.shared.application import Actor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from app.transport.http.public_v1.billing.dependencies import get_billing_workflow
from fastapi import APIRouter, Depends, status

router = APIRouter()


@router.post(
    "/portal-sessions",
    response_model=PortalSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_customer_portal_session(
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
) -> PortalSessionResponse:
    return workflow.create_portal(current_user)


@router.post("/subscription/resume", response_model=SubscriptionActionResponse)
def resume_subscription(
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> SubscriptionActionResponse:
    return workflow.resume(
        actor=current_user,
        operation=operation,
    )
