from app.bootstrap.workflows.billing import BillingWorkflow
from app.modules.billing.application.contracts import (
    CheckoutSessionResponse,
    CheckoutSessionStatusResponse,
    SubscriptionInterval,
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
    "/checkout-sessions",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_checkout_session(
    interval: SubscriptionInterval,
    workflow: BillingWorkflow = Depends(get_billing_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> CheckoutSessionResponse:
    return workflow.create_checkout(
        actor=current_user,
        operation=operation,
        interval=interval,
    )


@router.get(
    "/checkout-sessions/{session_id}",
    response_model=CheckoutSessionStatusResponse,
)
def session_status(
    session_id: str,
    workflow: BillingWorkflow = Depends(get_billing_workflow),
) -> CheckoutSessionStatusResponse:
    return workflow.checkout_status(session_id)
