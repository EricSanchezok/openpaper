"""Cloud-authenticated management API for Scholens AccessKeys."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.access_keys.application.contracts import (
    AccessKeyCreateRequest,
    AccessKeyCreateResponse,
    AccessKeyListResponse,
    AccessKeyResponse,
    AccessKeyUpdateRequest,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Query, Response, status

access_keys_router = APIRouter()


@access_keys_router.get("", response_model=AccessKeyListResponse)
def list_access_keys(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> AccessKeyListResponse:
    return executor.query(
        lambda capabilities: capabilities.access_keys.list(
            actor=actor,
            limit=limit,
            cursor=cursor,
        )
    )


@access_keys_router.post(
    "",
    response_model=AccessKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_access_key(
    request: AccessKeyCreateRequest,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> AccessKeyCreateResponse:
    return executor.command(
        lambda capabilities: capabilities.access_keys.create(
            actor=actor,
            operation=operation,
            request=request,
        )
    )


@access_keys_router.patch(
    "/{access_key_id}",
    response_model=AccessKeyResponse,
)
def update_access_key(
    access_key_id: UUID,
    request: AccessKeyUpdateRequest,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> AccessKeyResponse:
    return executor.command(
        lambda capabilities: capabilities.access_keys.update(
            actor=actor,
            operation=operation,
            access_key_id=access_key_id,
            request=request,
        )
    )


@access_keys_router.delete(
    "/{access_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_access_key(
    access_key_id: UUID,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.access_keys.revoke(
            actor=actor,
            operation=operation,
            access_key_id=access_key_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
