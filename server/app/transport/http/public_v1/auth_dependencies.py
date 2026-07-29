from __future__ import annotations

from typing import Annotated

from app.bootstrap.container import build_identity, optional_cloud_user_dependency
from app.database.database import get_db
from app.modules.identity.application import AuthenticatedIdentity
from app.shared.application import Actor
from cloud_auth.models.user import UserRecord
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session


async def get_current_user(
    cloud_user: Annotated[
        UserRecord | None,
        Depends(optional_cloud_user_dependency),
    ],
    db: Session = Depends(get_db),
) -> Actor | None:
    if cloud_user is None:
        return None

    return build_identity(db=db).resolve_actor(
        AuthenticatedIdentity(
            id=cloud_user.id,
            email=cloud_user.email,
            display_name=cloud_user.display_name,
            status=cloud_user.status,
            email_verified=cloud_user.email_verified,
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
