"""Authenticated caller context passed to application use cases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr


class Actor(BaseModel):
    """The product identity required to authorize a business operation.

    Transport-specific credentials and sanchezcloud-identity records are deliberately not
    exposed beyond the identity adapter.
    """

    model_config = ConfigDict(frozen=True)

    id: int
    email: EmailStr
    display_name: str | None = None
    status: str
    email_verified: bool
    locale: str | None = None
    is_admin: bool = False
    is_blocked: bool = False
    is_active: bool = True

    @classmethod
    def from_identity_projection(
        cls,
        *,
        user_id: int,
        email: str,
        display_name: str | None,
        status: str,
        email_verified: bool,
        locale: str | None = None,
        is_admin: bool = False,
        is_blocked: bool = False,
    ) -> Actor:
        """Map scalar identity/profile fields without importing their storage model."""
        return cls(
            id=user_id,
            email=email,
            display_name=display_name,
            status=status,
            email_verified=email_verified,
            locale=locale,
            is_admin=is_admin,
            is_blocked=is_blocked,
            is_active=status == "active",
        )
