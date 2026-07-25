from __future__ import annotations

from typing import TYPE_CHECKING, Self

from cloud_auth.models.user import AccountStatus
from pydantic import BaseModel, ConfigDict, EmailStr

if TYPE_CHECKING:
    from app.database.models import AuthUser


class CurrentUser(BaseModel):
    """Authenticated cloud-auth identity enriched with Scholens product state."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    display_name: str | None = None
    status: AccountStatus
    email_verified: bool
    locale: str | None = None
    is_admin: bool = False
    is_blocked: bool = False
    is_active: bool = False

    @classmethod
    def from_auth_user(cls, user: AuthUser) -> Self:
        profile = user.profile
        return cls(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            status=user.status,
            email_verified=user.email_verified_at is not None,
            locale=profile.locale if profile else None,
            is_admin=profile.is_admin if profile else False,
            is_blocked=profile.is_blocked if profile else False,
            is_active=user.status == "active",
        )
