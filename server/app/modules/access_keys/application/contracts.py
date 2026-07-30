"""Transport-neutral AccessKey commands and responses."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated
from typing import cast
from uuid import UUID

from app.modules.access_keys.domain import AccessKeyStatus
from app.shared.application import Actor
from app.shared.domain import (
    WorkspacePermission,
    ordered_workspace_permissions,
)
from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


def _normalize_name(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def _normalize_permissions(value: object) -> object:
    if not isinstance(value, (list, tuple)):
        return value
    return ordered_workspace_permissions(
        cast(Iterable[WorkspacePermission | str], value)
    )


AccessKeyName = Annotated[
    str,
    BeforeValidator(_normalize_name),
    Field(min_length=1, max_length=80),
]
AccessKeyPermissions = Annotated[
    list[WorkspacePermission],
    BeforeValidator(_normalize_permissions),
    Field(min_length=1, max_length=3),
]


class AccessKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AccessKeyName
    permissions: AccessKeyPermissions
    expires_at: AwareDatetime | None = None

    @field_validator("expires_at")
    @classmethod
    def normalize_expiration(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return value.astimezone(timezone.utc) if value is not None else None


class AccessKeyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AccessKeyName | None = None
    permissions: AccessKeyPermissions | None = None

    @model_validator(mode="after")
    def require_change(self) -> AccessKeyUpdateRequest:
        updated_fields = self.model_fields_set.intersection({"name", "permissions"})
        if not updated_fields:
            raise ValueError("at least one field must be provided")
        if "name" in updated_fields and self.name is None:
            raise ValueError("name cannot be null")
        if "permissions" in updated_fields and self.permissions is None:
            raise ValueError("permissions cannot be null")
        return self


class AccessKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    permissions: list[WorkspacePermission]
    status: AccessKeyStatus
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class AccessKeyCreateResponse(BaseModel):
    access_key: AccessKeyResponse
    secret: str


class AccessKeyListResponse(BaseModel):
    items: list[AccessKeyResponse]
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedAccessKey:
    access_key_id: UUID
    actor: Actor
    permissions: frozenset[WorkspacePermission]
