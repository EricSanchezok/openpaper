"""Cloud-authenticated management of user-owned research Connectors."""

from __future__ import annotations

from app.bootstrap.execution import get_connector_workflow
from app.bootstrap.workflows.connectors import ConnectorWorkflow
from app.modules.integrations.connectors.application import (
    ConnectorConnectRequest,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorUpdateRequest,
)
from app.modules.integrations.connectors.domain import ConnectorProvider
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Response, status

connectors_router = APIRouter(tags=["connectors"])


def _connector_provider(value: str) -> ConnectorProvider:
    try:
        return ConnectorProvider(value)
    except ValueError as exc:
        raise AppError(
            code="connector_not_supported",
            message="Connector provider is not supported",
            kind=FailureKind.NOT_FOUND,
        ) from exc


@connectors_router.get("", response_model=ConnectorListResponse)
def list_connectors(
    workflow: ConnectorWorkflow = Depends(get_connector_workflow),
    actor: Actor = Depends(get_required_user),
) -> ConnectorListResponse:
    return workflow.list(actor=actor)


@connectors_router.put("/{provider}", response_model=ConnectorResponse)
async def connect_connector(
    provider: str,
    request: ConnectorConnectRequest,
    workflow: ConnectorWorkflow = Depends(get_connector_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ConnectorResponse:
    return await workflow.connect(
        actor=actor,
        operation=operation,
        provider=_connector_provider(provider),
        api_key=request.api_key.get_secret_value(),
    )


@connectors_router.patch("/{provider}", response_model=ConnectorResponse)
async def update_connector(
    provider: str,
    request: ConnectorUpdateRequest,
    workflow: ConnectorWorkflow = Depends(get_connector_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ConnectorResponse:
    return await workflow.set_enabled(
        actor=actor,
        operation=operation,
        provider=_connector_provider(provider),
        enabled=request.enabled,
    )


@connectors_router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_connector(
    provider: str,
    workflow: ConnectorWorkflow = Depends(get_connector_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    workflow.disconnect(
        actor=actor,
        operation=operation,
        provider=_connector_provider(provider),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
