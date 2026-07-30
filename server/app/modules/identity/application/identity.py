"""Scholens identity/profile use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.identity.application.contracts import (
    SetUserBlockedRequest,
    SetUserBlockedResponse,
)
from app.modules.identity.domain import (
    AccountAccessFacts,
    require_administrator,
    require_product_access,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


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


@dataclass(frozen=True, slots=True)
class LocalIdentity:
    id: int
    email: str
    display_name: str | None
    status: str
    email_verified: bool
    profile: IdentityProfile


class IdentityGateway(Protocol):
    def ensure_profile(self, *, user_id: int) -> IdentityProfile: ...

    def local_identity(self, *, user_id: int) -> LocalIdentity | None: ...

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
        profile = self._gateway.ensure_profile(user_id=identity.id)
        return self._actor(
            user_id=identity.id,
            email=identity.email,
            display_name=identity.display_name,
            status=identity.status,
            email_verified=identity.email_verified,
            profile=profile,
        )

    def resolve_actor_by_user_id(self, user_id: int) -> Actor:
        identity = self._gateway.local_identity(user_id=user_id)
        if identity is None:
            raise AppError(
                code="identity_profile_incomplete",
                message="The local identity profile is unavailable",
                kind=FailureKind.NOT_FOUND,
            )
        return self._actor(
            user_id=identity.id,
            email=identity.email,
            display_name=identity.display_name,
            status=identity.status,
            email_verified=identity.email_verified,
            profile=identity.profile,
        )

    @staticmethod
    def _actor(
        *,
        user_id: int,
        email: str,
        display_name: str | None,
        status: str,
        email_verified: bool,
        profile: IdentityProfile,
    ) -> Actor:
        facts = AccountAccessFacts(
            status=status,
            is_blocked=profile.is_blocked,
            is_admin=profile.is_admin,
        )
        require_product_access(facts)
        return Actor(
            id=user_id,
            email=email,
            display_name=display_name,
            status=status,
            email_verified=email_verified,
            locale=profile.locale,
            is_admin=profile.is_admin,
            is_blocked=profile.is_blocked,
            is_active=facts.is_active,
        )

    def set_blocked(
        self,
        *,
        actor: Actor,
        user_id: int,
        request: SetUserBlockedRequest,
    ) -> SetUserBlockedResponse:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )
        target_email = self._gateway.set_blocked(
            user_id=user_id,
            blocked=request.blocked,
        )
        if target_email is None:
            raise AppError(
                code="user_not_found",
                message="User not found",
                kind=FailureKind.NOT_FOUND,
            )
        action = "blocked" if request.blocked else "unblocked"
        return SetUserBlockedResponse(
            success=True,
            message=f"User {action} successfully",
        )
