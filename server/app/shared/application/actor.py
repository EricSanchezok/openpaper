"""Authenticated caller context passed to application use cases."""

from pydantic import BaseModel, ConfigDict, EmailStr


class Actor(BaseModel):
    """The product identity required to authorize a business operation.

    Transport-specific credentials and cloud-auth records are deliberately not
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
