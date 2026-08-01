from __future__ import annotations

from typing import Annotated
from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.container import optional_identity_user_dependency
from app.bootstrap.execution import (
    get_application_executor,
    get_operation_context_factory,
)
from app.modules.identity.application import AuthenticatedIdentity
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from sanchezcloud_identity.models.user import UserRecord
from fastapi import Depends, HTTPException, Request, status
from app.transport.http.observability import (
    attach_operation_context,
    ensure_request_id,
)


async def get_current_user(
    request: Request,
    identity_user: Annotated[
        UserRecord | None,
        Depends(optional_identity_user_dependency),
    ],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    operation_factory: OperationContextFactory = Depends(get_operation_context_factory),
) -> Actor | None:
    if identity_user is None:
        return None

    identity = AuthenticatedIdentity(
        id=identity_user.id,
        email=identity_user.email,
        display_name=identity_user.display_name,
        status=identity_user.status,
        email_verified=identity_user.email_verified,
    )
    operation = operation_factory.root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(
            request=RequestReference(
                request_id=ensure_request_id(request),
            )
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )
    actor = executor.command(
        lambda capabilities: capabilities.identity.resolve_actor(
            identity,
            operation=operation,
        )
    )
    request.state.authenticated = True
    attach_operation_context(request, operation, actor_id=str(actor.id))
    return actor


async def get_required_user(
    current_user: Annotated[Actor | None, Depends(get_current_user)],
) -> Actor:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_required_operation(
    request: Request,
    _current_user: Annotated[Actor, Depends(get_required_user)],
) -> OperationContext:
    operation = getattr(request.state, "operation_context", None)
    if not isinstance(operation, OperationContext):
        raise RuntimeError("authenticated_operation_context_missing")
    return operation


async def get_admin_user(
    current_user: Annotated[Actor, Depends(get_required_user)],
) -> Actor:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user
