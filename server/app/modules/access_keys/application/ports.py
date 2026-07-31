"""Application ports for AccessKey persistence and secret handling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.shared.application import Actor
from app.shared.domain import WorkspacePermission


@dataclass(frozen=True, slots=True)
class AccessKeyRecord:
    id: UUID
    user_id: int
    name: str
    key_prefix: str
    permissions: tuple[WorkspacePermission, ...]
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AccessKeyListPosition:
    created_at: datetime
    id: UUID


class AccessKeyListDirection(StrEnum):
    OLDER = "older"
    NEWER = "newer"


@dataclass(frozen=True, slots=True)
class AccessKeyListCursor:
    direction: AccessKeyListDirection
    position: AccessKeyListPosition


@dataclass(frozen=True, slots=True)
class AccessKeyListPage:
    records: tuple[AccessKeyRecord, ...]
    has_more: bool


@dataclass(frozen=True, slots=True)
class GeneratedAccessKey:
    secret: str
    secret_hash: str
    key_prefix: str


class AccessKeyGateway(Protocol):
    def acquire_creation_lock(self, *, user_id: int) -> None: ...

    def count_active(self, *, user_id: int, now: datetime) -> int: ...

    def create(
        self,
        *,
        user_id: int,
        name: str,
        secret_hash: str,
        key_prefix: str,
        permissions: tuple[WorkspacePermission, ...],
        expires_at: datetime | None,
        now: datetime,
    ) -> AccessKeyRecord: ...

    def list_owned(
        self,
        *,
        user_id: int,
        limit: int,
        direction: AccessKeyListDirection,
        position: AccessKeyListPosition | None,
    ) -> AccessKeyListPage: ...

    def lock_owned(
        self,
        *,
        user_id: int,
        access_key_id: UUID,
    ) -> AccessKeyRecord | None: ...

    def lock_by_secret_hash(
        self,
        *,
        secret_hash: str,
    ) -> AccessKeyRecord | None: ...

    def update(
        self,
        *,
        access_key_id: UUID,
        name: str,
        permissions: tuple[WorkspacePermission, ...],
        now: datetime,
    ) -> AccessKeyRecord: ...

    def revoke(
        self,
        *,
        access_key_id: UUID,
        now: datetime,
    ) -> None: ...

    def touch_last_used(
        self,
        *,
        access_key_id: UUID,
        now: datetime,
        stale_before: datetime,
    ) -> None: ...


class AccessKeySecrets(Protocol):
    def generate(self) -> GeneratedAccessKey: ...

    def hash_if_valid(self, secret: str) -> str | None: ...


class ActorResolver(Protocol):
    def resolve_actor_by_user_id(self, user_id: int) -> Actor: ...
