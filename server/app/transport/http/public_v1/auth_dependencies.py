from __future__ import annotations

from typing import Annotated

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.container import optional_cloud_user_dependency
from app.bootstrap.execution import get_application_executor
from app.modules.identity.application import AuthenticatedIdentity
from app.shared.application import Actor, ApplicationExecutor
from cloud_auth.models.user import UserRecord
from fastapi import Depends, HTTPException, status


async def get_current_user(
    cloud_user: Annotated[
        UserRecord | None,
        Depends(optional_cloud_user_dependency),
    ],
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Actor | None:
    if cloud_user is None:
        return None

    identity = AuthenticatedIdentity(
        id=cloud_user.id,
        email=cloud_user.email,
        display_name=cloud_user.display_name,
        status=cloud_user.status,
        email_verified=cloud_user.email_verified,
    )
    return executor.query(
        lambda capabilities: capabilities.identity.resolve_actor(
            identity,
        )
    )


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


async def get_admin_user(
    current_user: Annotated[Actor, Depends(get_required_user)],
) -> Actor:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user
