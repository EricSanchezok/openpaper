"""HTTP dependency for the transaction-safe billing workflow."""

from typing import cast

from app.bootstrap.workflows.billing import BillingWorkflow
from fastapi import Request


def get_billing_workflow(request: Request) -> BillingWorkflow:
    return cast(BillingWorkflow, request.app.state.billing_workflow)


__all__ = ["get_billing_workflow"]
