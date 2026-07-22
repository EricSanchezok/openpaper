from __future__ import annotations

from cloud_auth.models.user import AccountStatus
from pydantic import BaseModel, ConfigDict, EmailStr


class CurrentUser(BaseModel):
    """Authenticated cloud-auth identity enriched with OpenPaper product state."""

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
