"""AccessKey management and authentication use cases."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NoReturn
from uuid import UUID

from app.modules.access_keys.application.contracts import (
    AccessKeyCreateRequest,
    AccessKeyCreateResponse,
    AccessKeyExpiration,
    AccessKeyListResponse,
    AccessKeyResponse,
    AccessKeyUpdateRequest,
    AuthenticatedAccessKey,
)
from app.modules.access_keys.application.ports import (
    AccessKeyGateway,
    AccessKeyListCursor,
    AccessKeyListDirection,
    AccessKeyListPosition,
    AccessKeyRecord,
    AccessKeySecrets,
    ActorResolver,
)
from app.modules.access_keys.domain import (
    AccessKeyFacts,
    AccessKeyStatus,
    access_key_status,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, Clock, OperationContext, SignedCursorCodec
from app.shared.domain import (
    AppError,
    FailureKind,
    WorkspacePermission,
    ordered_workspace_permissions,
)

MAX_ACTIVE_ACCESS_KEYS = 10
LAST_USED_WRITE_INTERVAL = timedelta(hours=1)
ACCESS_KEY_CURSOR_FINGERPRINT = "access-key-management"
ACCESS_KEY_CREATED = OperationAction("access_key.created")
ACCESS_KEY_UPDATED = OperationAction("access_key.updated")
ACCESS_KEY_REVOKED = OperationAction("access_key.revoked")
_EXPIRATION_DELTAS = {
    AccessKeyExpiration.SEVEN_DAYS: timedelta(days=7),
    AccessKeyExpiration.THIRTY_DAYS: timedelta(days=30),
    AccessKeyExpiration.NINETY_DAYS: timedelta(days=90),
}


class AccessKeys:
    def __init__(
        self,
        *,
        gateway: AccessKeyGateway,
        secrets: AccessKeySecrets,
        actors: ActorResolver,
        clock: Clock,
        cursors: SignedCursorCodec,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._secrets = secrets
        self._actors = actors
        self._clock = clock
        self._cursors = cursors
        self._journal = journal

    def create(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: AccessKeyCreateRequest,
    ) -> AccessKeyCreateResponse:
        now = self._clock.now()
        permissions = _require_permissions(request.permissions)
        generated = self._secrets.generate()
        self._gateway.acquire_creation_lock(user_id=actor.id)
        if self._gateway.count_active(user_id=actor.id, now=now) >= (
            MAX_ACTIVE_ACCESS_KEYS
        ):
            raise AppError(
                code="access_key_limit_reached",
                message="The active access key limit has been reached",
                kind=FailureKind.CONFLICT,
            )
        record = self._gateway.create(
            user_id=actor.id,
            name=request.name,
            secret_hash=generated.secret_hash,
            key_prefix=generated.key_prefix,
            permissions=permissions,
            expires_at=_expiration_time(request.expiration, now=now),
            now=now,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=ACCESS_KEY_CREATED,
            resources=(ResourceRef("access_key", str(record.id)),),
        )
        return AccessKeyCreateResponse(
            access_key=_response(record, now=now),
            secret=generated.secret,
        )

    def list(
        self,
        *,
        actor: Actor,
        limit: int = 20,
        cursor: str | None = None,
    ) -> AccessKeyListResponse:
        if not 1 <= limit <= 100:
            raise AppError(
                code="access_key_limit_invalid",
                message="Access key page size must be between 1 and 100",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        now = self._clock.now()
        decoded = self._decode_cursor(actor=actor, limit=limit, cursor=cursor)
        direction = (
            decoded.direction if decoded is not None else AccessKeyListDirection.OLDER
        )
        position = decoded.position if decoded is not None else None
        result = self._gateway.list_owned(
            user_id=actor.id,
            limit=limit,
            direction=direction,
            position=position,
        )
        page = result.records
        if not page:
            return AccessKeyListResponse(items=[])

        has_newer = (
            result.has_more
            if direction is AccessKeyListDirection.NEWER
            else position is not None
        )
        has_older = (
            result.has_more
            if direction is AccessKeyListDirection.OLDER
            else position is not None
        )
        return AccessKeyListResponse(
            items=[_response(record, now=now) for record in page],
            previous_cursor=(
                self._encode_cursor(
                    actor=actor,
                    limit=limit,
                    direction=AccessKeyListDirection.NEWER,
                    position=AccessKeyListPosition(
                        created_at=page[0].created_at,
                        id=page[0].id,
                    ),
                )
                if has_newer
                else None
            ),
            next_cursor=(
                self._encode_cursor(
                    actor=actor,
                    limit=limit,
                    direction=AccessKeyListDirection.OLDER,
                    position=AccessKeyListPosition(
                        created_at=page[-1].created_at,
                        id=page[-1].id,
                    ),
                )
                if has_older
                else None
            ),
        )

    def update(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        access_key_id: UUID,
        request: AccessKeyUpdateRequest,
    ) -> AccessKeyResponse:
        now = self._clock.now()
        record = self._require_owned_locked(
            user_id=actor.id,
            access_key_id=access_key_id,
        )
        if _status(record, now=now) is not AccessKeyStatus.ACTIVE:
            raise AppError(
                code="access_key_inactive",
                message="Only active access keys can be updated",
                kind=FailureKind.CONFLICT,
            )
        permissions = (
            _require_permissions(request.permissions)
            if request.permissions is not None
            else record.permissions
        )
        name = request.name if request.name is not None else record.name
        if name == record.name and permissions == record.permissions:
            return _response(record, now=now)
        updated = self._gateway.update(
            access_key_id=record.id,
            name=name,
            permissions=permissions,
            now=now,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=ACCESS_KEY_UPDATED,
            resources=(ResourceRef("access_key", str(record.id)),),
        )
        return _response(updated, now=now)

    def revoke(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        access_key_id: UUID,
    ) -> None:
        now = self._clock.now()
        record = self._require_owned_locked(
            user_id=actor.id,
            access_key_id=access_key_id,
        )
        if _status(record, now=now) is AccessKeyStatus.ACTIVE:
            self._gateway.revoke(access_key_id=record.id, now=now)
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ACCESS_KEY_REVOKED,
                resources=(ResourceRef("access_key", str(record.id)),),
            )

    def authenticate(self, secret: str) -> AuthenticatedAccessKey:
        now = self._clock.now()
        secret_hash = self._secrets.hash_if_valid(secret)
        if secret_hash is None:
            _raise_invalid_access_key()
        record = self._gateway.lock_by_secret_hash(secret_hash=secret_hash)
        if record is None or _status(record, now=now) is not AccessKeyStatus.ACTIVE:
            _raise_invalid_access_key()
        try:
            actor = self._actors.resolve_actor_by_user_id(record.user_id)
        except AppError as error:
            if error.kind in {
                FailureKind.DEPENDENCY_FAILURE,
                FailureKind.UNAVAILABLE,
            }:
                raise AppError(
                    code="access_key_authentication_unavailable",
                    message="Access key authentication is temporarily unavailable",
                    kind=FailureKind.UNAVAILABLE,
                ) from error
            _raise_invalid_access_key()
        self._gateway.touch_last_used(
            access_key_id=record.id,
            now=now,
            stale_before=now - LAST_USED_WRITE_INTERVAL,
        )
        return AuthenticatedAccessKey(
            access_key_id=record.id,
            actor=actor,
            permissions=frozenset(record.permissions),
        )

    def _require_owned_locked(
        self,
        *,
        user_id: int,
        access_key_id: UUID,
    ) -> AccessKeyRecord:
        record = self._gateway.lock_owned(
            user_id=user_id,
            access_key_id=access_key_id,
        )
        if record is None:
            raise AppError(
                code="access_key_not_found",
                message="Access key not found",
                kind=FailureKind.NOT_FOUND,
            )
        return record

    def _decode_cursor(
        self,
        *,
        actor: Actor,
        limit: int,
        cursor: str | None,
    ) -> AccessKeyListCursor | None:
        if cursor is None:
            return None
        try:
            direction_raw, created_at_raw, id_raw = self._cursors.decode_keyset(
                cursor=cursor,
                fingerprint=self._cursor_binding(actor, limit=limit),
                arity=3,
            )
            created_at = datetime.fromisoformat(created_at_raw)
            if created_at.tzinfo is None:
                raise ValueError("cursor datetime must be timezone-aware")
            return AccessKeyListCursor(
                direction=AccessKeyListDirection(direction_raw),
                position=AccessKeyListPosition(
                    created_at=created_at,
                    id=UUID(id_raw),
                ),
            )
        except (TypeError, ValueError) as error:
            raise AppError(
                code="access_key_cursor_invalid",
                message="The access key cursor is invalid or expired",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from error

    def _encode_cursor(
        self,
        *,
        actor: Actor,
        limit: int,
        direction: AccessKeyListDirection,
        position: AccessKeyListPosition,
    ) -> str:
        return self._cursors.encode_keyset(
            fingerprint=self._cursor_binding(actor, limit=limit),
            values=(
                direction.value,
                position.created_at.isoformat(),
                str(position.id),
            ),
        )

    @staticmethod
    def _cursor_binding(actor: Actor, *, limit: int) -> str:
        return (
            f"{ACCESS_KEY_CURSOR_FINGERPRINT}:v2:{actor.id}:"
            f"created_at-desc:id-desc:limit={limit}"
        )


def _require_permissions(
    permissions: list[WorkspacePermission],
) -> tuple[WorkspacePermission, ...]:
    normalized = tuple(ordered_workspace_permissions(permissions))
    if not normalized:
        raise AppError(
            code="access_key_permissions_required",
            message="At least one workspace permission is required",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    return normalized


def _expiration_time(
    expiration: AccessKeyExpiration,
    *,
    now: datetime,
) -> datetime | None:
    if expiration is AccessKeyExpiration.NEVER:
        return None
    return now + _EXPIRATION_DELTAS[expiration]


def _status(record: AccessKeyRecord, *, now: datetime) -> AccessKeyStatus:
    return access_key_status(
        AccessKeyFacts(
            expires_at=record.expires_at,
            revoked_at=record.revoked_at,
        ),
        now=now,
    )


def _response(record: AccessKeyRecord, *, now: datetime) -> AccessKeyResponse:
    return AccessKeyResponse(
        id=record.id,
        name=record.name,
        key_prefix=record.key_prefix,
        permissions=list(record.permissions),
        status=_status(record, now=now),
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
    )


def _raise_invalid_access_key() -> NoReturn:
    raise AppError(
        code="invalid_access_key",
        message="The access key is invalid",
        kind=FailureKind.UNAUTHENTICATED,
    )
