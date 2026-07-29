"""Scholens identity/profile use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.identity.application.contracts import (
    SetUserBlockedRequest,
    SetUserBlockedResponse,
)
from app.shared.application import Actor
from app.shared.domain import AppError


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    id: int
    email: str
    display_name: str | None
    status: str
    email_verified: bool


@dataclass(frozen=True, slots=True)
class IdentityProfile:
    locale: str | None
    is_admin: bool
    is_blocked: bool


class IdentityGateway(Protocol):
    def profile(self, *, user_id: int) -> IdentityProfile: ...

    def set_blocked(
        self,
        *,
        user_id: int,
        blocked: bool,
    ) -> str | None: ...


class Identity:
    def __init__(self, gateway: IdentityGateway) -> None:
        self._gateway = gateway

    def resolve_actor(self, identity: AuthenticatedIdentity) -> Actor:
        profile = self._gateway.profile(user_id=identity.id)
        if profile.is_blocked:
            raise AppError(
                code="identity_suspended",
                message="Scholens access is suspended",
                status_code=403,
            )
        return Actor(
            id=identity.id,
            email=identity.email,
            display_name=identity.display_name,
            status=identity.status,
            email_verified=identity.email_verified,
            locale=profile.locale,
            is_admin=profile.is_admin,
            is_blocked=profile.is_blocked,
            is_active=True,
        )

    def set_blocked(
        self,
        *,
        actor: Actor,
        user_id: int,
        request: SetUserBlockedRequest,
    ) -> SetUserBlockedResponse:
        if not actor.is_admin:
            raise AppError(
                code="admin_required",
                message="Administrator access is required",
                status_code=403,
            )
        target_email = self._gateway.set_blocked(
            user_id=user_id,
            blocked=request.blocked,
        )
        if target_email is None:
            raise AppError(
                code="user_not_found",
                message="User not found",
                status_code=404,
            )
        action = "blocked" if request.blocked else "unblocked"
        return SetUserBlockedResponse(
            success=True,
            message=f"User {action} successfully",
        )
