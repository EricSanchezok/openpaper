from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from app.main import app
from app.modules.access_keys.application.access_keys import AccessKeys
from app.modules.access_keys.application.contracts import (
    AccessKeyCreateRequest,
    AccessKeyExpiration,
    AccessKeyUpdateRequest,
)
from app.modules.access_keys.application.ports import (
    AccessKeyListDirection,
    AccessKeyListPage,
    AccessKeyListPosition,
    AccessKeyRecord,
    GeneratedAccessKey,
)
from app.modules.access_keys.domain import (
    AccessKeyFacts,
    AccessKeyStatus,
    access_key_status,
)
from app.modules.access_keys.infrastructure.models import AccessKey
from app.modules.access_keys.infrastructure.secrets import SecureAccessKeySecrets
from app.modules.identity.application.identity import (
    AuthenticatedIdentity,
    Identity,
    IdentityProfile,
    IdentityProfileResolution,
    LocalIdentity,
)
from app.modules.operation_journal.application import OperationJournal
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    SignedCursorCodec,
)
from app.shared.domain import AppError, WorkspacePermission
from app.shared.domain import FailureKind
from pydantic import ValidationError
from unittest.mock import MagicMock

NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Secrets:
    secret = "sk_scholens_" + "a" * 43
    secret_hash = "b" * 64

    def generate(self) -> GeneratedAccessKey:
        return GeneratedAccessKey(
            secret=self.secret,
            secret_hash=self.secret_hash,
            key_prefix=self.secret[:20],
        )

    def hash_if_valid(self, secret: str) -> str | None:
        return self.secret_hash if secret == self.secret else None


class _Actors:
    def resolve_actor_by_user_id(self, user_id: int) -> Actor:
        return _actor(user_id)


class _Gateway:
    def __init__(self) -> None:
        self.records: dict[UUID, AccessKeyRecord] = {}
        self.hashes: dict[str, UUID] = {}
        self.locked_users: list[int] = []
        self.touched: list[UUID] = []

    def acquire_creation_lock(self, *, user_id: int) -> None:
        self.locked_users.append(user_id)

    def count_active(self, *, user_id: int, now: datetime) -> int:
        return sum(
            record.user_id == user_id
            and access_key_status(
                AccessKeyFacts(record.expires_at, record.revoked_at),
                now=now,
            )
            is AccessKeyStatus.ACTIVE
            for record in self.records.values()
        )

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
    ) -> AccessKeyRecord:
        record = AccessKeyRecord(
            id=uuid4(),
            user_id=user_id,
            name=name,
            key_prefix=key_prefix,
            permissions=permissions,
            expires_at=expires_at,
            revoked_at=None,
            last_used_at=None,
            created_at=now,
            updated_at=now,
        )
        self.records[record.id] = record
        self.hashes[secret_hash] = record.id
        return record

    def list_owned(
        self,
        *,
        user_id: int,
        limit: int,
        direction: AccessKeyListDirection,
        position: AccessKeyListPosition | None,
    ) -> AccessKeyListPage:
        records = sorted(
            (
                record
                for record in self.records.values()
                if record.user_id == user_id
                and (
                    position is None
                    or (
                        direction is AccessKeyListDirection.OLDER
                        and (record.created_at, record.id)
                        < (position.created_at, position.id)
                    )
                    or (
                        direction is AccessKeyListDirection.NEWER
                        and (record.created_at, record.id)
                        > (position.created_at, position.id)
                    )
                )
            ),
            key=lambda record: (record.created_at, record.id),
            reverse=direction is AccessKeyListDirection.OLDER,
        )
        page = records[:limit]
        if direction is AccessKeyListDirection.NEWER:
            page.reverse()
        return AccessKeyListPage(
            records=tuple(page),
            has_more=len(records) > limit,
        )

    def lock_owned(
        self,
        *,
        user_id: int,
        access_key_id: UUID,
    ) -> AccessKeyRecord | None:
        record = self.records.get(access_key_id)
        return record if record is not None and record.user_id == user_id else None

    def lock_by_secret_hash(self, *, secret_hash: str) -> AccessKeyRecord | None:
        access_key_id = self.hashes.get(secret_hash)
        return self.records.get(access_key_id) if access_key_id is not None else None

    def update(
        self,
        *,
        access_key_id: UUID,
        name: str,
        permissions: tuple[WorkspacePermission, ...],
        now: datetime,
    ) -> AccessKeyRecord:
        record = replace(
            self.records[access_key_id],
            name=name,
            permissions=permissions,
            updated_at=now,
        )
        self.records[access_key_id] = record
        return record

    def revoke(self, *, access_key_id: UUID, now: datetime) -> None:
        self.records[access_key_id] = replace(
            self.records[access_key_id],
            revoked_at=now,
            updated_at=now,
        )

    def touch_last_used(
        self,
        *,
        access_key_id: UUID,
        now: datetime,
        stale_before: datetime,
    ) -> None:
        record = self.records[access_key_id]
        if record.last_used_at is None or record.last_used_at <= stale_before:
            self.records[access_key_id] = replace(record, last_used_at=now)
            self.touched.append(access_key_id)


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email=f"reader-{user_id}@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _application(gateway: _Gateway) -> AccessKeys:
    return AccessKeys(
        gateway=gateway,
        secrets=_Secrets(),
        actors=_Actors(),
        clock=_Clock(),
        cursors=SignedCursorCodec(
            "x" * 32,
            revision="access-keys-v2",
            error_code="access_key_cursor_invalid",
            error_kind=FailureKind.INVALID_ARGUMENT,
        ),
        journal=MagicMock(spec=OperationJournal),
    )


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (AccessKeyFacts(None, None), AccessKeyStatus.ACTIVE),
        (AccessKeyFacts(NOW + timedelta(seconds=1), None), AccessKeyStatus.ACTIVE),
        (AccessKeyFacts(NOW, None), AccessKeyStatus.EXPIRED),
        (
            AccessKeyFacts(NOW + timedelta(days=1), NOW),
            AccessKeyStatus.REVOKED,
        ),
    ],
)
def test_access_key_status_is_derived(
    facts: AccessKeyFacts,
    expected: AccessKeyStatus,
) -> None:
    assert access_key_status(facts, now=NOW) is expected


def test_secret_is_strict_random_and_one_way() -> None:
    secrets = SecureAccessKeySecrets()
    first = secrets.generate()
    second = secrets.generate()

    assert first.secret.startswith("sk_scholens_")
    assert len(first.secret) == 55
    assert first.secret != second.secret
    assert first.secret not in first.secret_hash
    assert secrets.hash_if_valid(first.secret) == first.secret_hash
    assert secrets.hash_if_valid(f"{first.secret}=") is None


def test_management_lifecycle_normalizes_permissions_and_hides_secret() -> None:
    gateway = _Gateway()
    access_keys = _application(gateway)
    created = access_keys.create(
        actor=_actor(),
        operation=_operation(),
        request=AccessKeyCreateRequest(
            name="  Claude Desktop  ",
            permissions=[
                WorkspacePermission.WRITE,
                WorkspacePermission.READ,
                WorkspacePermission.READ,
                WorkspacePermission.READ,
            ],
        ),
    )

    assert created.secret == _Secrets.secret
    assert created.access_key.name == "Claude Desktop"
    assert created.access_key.permissions == [
        WorkspacePermission.READ,
        WorkspacePermission.WRITE,
    ]
    assert created.access_key.expires_at == NOW + timedelta(days=30)
    assert gateway.locked_users == [7]

    updated = access_keys.update(
        actor=_actor(),
        operation=_operation(),
        access_key_id=created.access_key.id,
        request=AccessKeyUpdateRequest(permissions=[WorkspacePermission.DELETE]),
    )
    assert updated.permissions == [WorkspacePermission.DELETE]

    access_keys.revoke(
        actor=_actor(),
        operation=_operation(),
        access_key_id=created.access_key.id,
    )
    access_keys.revoke(
        actor=_actor(),
        operation=_operation(),
        access_key_id=created.access_key.id,
    )
    assert gateway.records[created.access_key.id].revoked_at == NOW


def test_authentication_is_uniform_and_touches_only_successful_keys() -> None:
    gateway = _Gateway()
    access_keys = _application(gateway)
    created = access_keys.create(
        actor=_actor(),
        operation=_operation(),
        request=AccessKeyCreateRequest(
            name="Agent",
            permissions=[WorkspacePermission.READ],
        ),
    )

    authenticated = access_keys.authenticate(created.secret)
    replayed = access_keys.authenticate(created.secret)
    assert authenticated.access_key_id == created.access_key.id
    assert replayed.access_key_id == created.access_key.id
    assert authenticated.permissions == frozenset({WorkspacePermission.READ})
    assert gateway.touched == [created.access_key.id]

    access_keys.revoke(
        actor=_actor(),
        operation=_operation(),
        access_key_id=created.access_key.id,
    )
    with pytest.raises(AppError) as error:
        access_keys.authenticate(created.secret)
    assert error.value.code == "invalid_access_key"
    assert gateway.touched == [created.access_key.id]


def test_active_capacity_and_stable_keyset_pagination() -> None:
    gateway = _Gateway()
    access_keys = _application(gateway)
    created_ids = [
        access_keys.create(
            actor=_actor(),
            operation=_operation(),
            request=AccessKeyCreateRequest(
                name=f"Agent {index}",
                permissions=[WorkspacePermission.READ],
            ),
        ).access_key.id
        for index in range(10)
    ]

    with pytest.raises(AppError) as capacity_error:
        access_keys.create(
            actor=_actor(),
            operation=_operation(),
            request=AccessKeyCreateRequest(
                name="One too many",
                permissions=[WorkspacePermission.READ],
            ),
        )
    assert capacity_error.value.code == "access_key_limit_reached"

    expected = sorted(created_ids, reverse=True)
    first = access_keys.list(actor=_actor(), limit=4)
    assert [item.id for item in first.items] == expected[:4]
    assert first.previous_cursor is None
    assert first.next_cursor is not None
    second = access_keys.list(
        actor=_actor(),
        limit=4,
        cursor=first.next_cursor,
    )
    assert [item.id for item in second.items] == expected[4:8]
    assert second.previous_cursor is not None
    assert second.next_cursor is not None
    third = access_keys.list(
        actor=_actor(),
        limit=4,
        cursor=second.next_cursor,
    )
    assert [item.id for item in third.items] == expected[8:]
    assert third.previous_cursor is not None
    assert third.next_cursor is None

    back_to_second = access_keys.list(
        actor=_actor(),
        limit=4,
        cursor=third.previous_cursor,
    )
    assert [item.id for item in back_to_second.items] == expected[4:8]
    assert back_to_second.previous_cursor is not None
    assert back_to_second.next_cursor is not None

    back_to_first = access_keys.list(
        actor=_actor(),
        limit=4,
        cursor=back_to_second.previous_cursor,
    )
    assert [item.id for item in back_to_first.items] == expected[:4]
    assert back_to_first.previous_cursor is None
    assert back_to_first.next_cursor is not None

    tampered_cursor = ("A" if first.next_cursor[0] != "A" else "B") + first.next_cursor[
        1:
    ]
    for actor, limit, cursor in (
        (_actor(8), 4, first.next_cursor),
        (_actor(), 5, first.next_cursor),
        (_actor(), 4, tampered_cursor),
    ):
        with pytest.raises(AppError) as invalid:
            access_keys.list(actor=actor, limit=limit, cursor=cursor)
        assert invalid.value.code == "access_key_cursor_invalid"
        assert invalid.value.kind is FailureKind.INVALID_ARGUMENT

    invalid_direction = SignedCursorCodec(
        "x" * 32,
        revision="access-keys-v2",
        error_code="access_key_cursor_invalid",
    ).encode_keyset(
        fingerprint="access-key-management:v2:7:created_at-desc:id-desc:limit=4",
        values=("sideways", NOW.isoformat(), str(created_ids[0])),
    )
    with pytest.raises(AppError) as malformed:
        access_keys.list(actor=_actor(), limit=4, cursor=invalid_direction)
    assert malformed.value.code == "access_key_cursor_invalid"

    legacy_cursor = SignedCursorCodec(
        "x" * 32,
        revision="access-keys-v1",
        error_code="access_key_cursor_invalid",
    ).encode_keyset(
        fingerprint="access-key-management:7",
        values=(NOW.isoformat(), str(created_ids[0])),
    )
    with pytest.raises(AppError) as legacy:
        access_keys.list(actor=_actor(), limit=4, cursor=legacy_cursor)
    assert legacy.value.code == "access_key_cursor_invalid"

    access_keys.revoke(
        actor=_actor(),
        operation=_operation(),
        access_key_id=created_ids[0],
    )
    replacement = access_keys.create(
        actor=_actor(),
        operation=_operation(),
        request=AccessKeyCreateRequest(
            name="Replacement",
            permissions=[WorkspacePermission.WRITE],
        ),
    )
    assert replacement.access_key.status is AccessKeyStatus.ACTIVE


def test_inactive_and_non_owned_keys_cannot_be_updated() -> None:
    gateway = _Gateway()
    access_keys = _application(gateway)
    created = access_keys.create(
        actor=_actor(),
        operation=_operation(),
        request=AccessKeyCreateRequest(
            name="Agent",
            permissions=[WorkspacePermission.READ],
        ),
    )
    access_keys.revoke(
        actor=_actor(),
        operation=_operation(),
        access_key_id=created.access_key.id,
    )

    with pytest.raises(AppError) as inactive:
        access_keys.update(
            actor=_actor(),
            operation=_operation(),
            access_key_id=created.access_key.id,
            request=AccessKeyUpdateRequest(name="Renamed"),
        )
    assert inactive.value.code == "access_key_inactive"

    with pytest.raises(AppError) as missing:
        access_keys.update(
            actor=_actor(8),
            operation=_operation(),
            access_key_id=created.access_key.id,
            request=AccessKeyUpdateRequest(name="Stolen"),
        )
    assert missing.value.code == "access_key_not_found"


@pytest.mark.parametrize(
    ("expiration", "expected"),
    [
        (AccessKeyExpiration.SEVEN_DAYS, NOW + timedelta(days=7)),
        (AccessKeyExpiration.THIRTY_DAYS, NOW + timedelta(days=30)),
        (AccessKeyExpiration.NINETY_DAYS, NOW + timedelta(days=90)),
        (AccessKeyExpiration.NEVER, None),
    ],
)
def test_fixed_expiration_options(
    expiration: AccessKeyExpiration,
    expected: datetime | None,
) -> None:
    created = _application(_Gateway()).create(
        actor=_actor(),
        operation=_operation(),
        request=AccessKeyCreateRequest(
            name="Agent",
            permissions=[WorkspacePermission.READ],
            expiration=expiration,
        ),
    )
    assert created.access_key.expires_at == expected


def test_expiration_contract_and_openapi_management_surface() -> None:
    default_request = AccessKeyCreateRequest(
        name="Default",
        permissions=[WorkspacePermission.READ],
    )
    assert default_request.expiration is AccessKeyExpiration.THIRTY_DAYS

    base_request = {
        "name": "Invalid",
        "permissions": ["read"],
    }
    for invalid_field in (
        {"expiration": None},
        {"expiration": "1_day"},
        {"expires_at": NOW.isoformat()},
    ):
        with pytest.raises(ValidationError):
            AccessKeyCreateRequest.model_validate(
                {
                    **base_request,
                    **invalid_field,
                }
            )

    for invalid_update in (
        {"expiration": "90_days"},
        {"expires_at": (NOW + timedelta(days=90)).isoformat()},
    ):
        with pytest.raises(ValidationError):
            AccessKeyUpdateRequest.model_validate(invalid_update)

    created = _application(_Gateway()).create(
        actor=_actor(),
        operation=_operation(),
        request=AccessKeyCreateRequest(
            name="Default",
            permissions=[WorkspacePermission.READ],
        ),
    )
    assert created.access_key.expires_at == NOW + timedelta(days=30)

    paths = app.openapi()["paths"]
    assert set(paths["/api/v1/me/access-keys"]) >= {"get", "post"}
    assert set(paths["/api/v1/me/access-keys/{access_key_id}"]) >= {
        "patch",
        "delete",
    }
    schemas = app.openapi()["components"]["schemas"]
    create_properties = schemas["AccessKeyCreateRequest"]["properties"]
    assert create_properties["expiration"]["default"] == "30_days"
    assert "expires_at" not in create_properties
    assert schemas["AccessKeyExpiration"]["enum"] == [
        "7_days",
        "30_days",
        "90_days",
        "never",
    ]
    update_properties = schemas["AccessKeyUpdateRequest"]["properties"]
    assert "expiration" not in update_properties
    assert "expires_at" not in update_properties
    list_properties = schemas["AccessKeyListResponse"]["properties"]
    assert {"previous_cursor", "next_cursor"} <= set(list_properties)
    assert AccessKey.__table__.c.secret_hash.unique is None
    assert any(index.unique for index in AccessKey.__table__.indexes)
    assert "secret" not in AccessKey.__table__.c


class _IdentityGateway:
    def __init__(self, *, status: str = "active", blocked: bool = False) -> None:
        self.profile = IdentityProfile(
            locale="en",
            is_admin=False,
            is_blocked=blocked,
        )
        self.local = LocalIdentity(
            id=7,
            email="reader@example.com",
            display_name="Reader",
            status=status,
            email_verified=True,
            profile=self.profile,
        )

    def resolve_profile(self, *, user_id: int) -> IdentityProfileResolution:
        assert user_id == 7
        return IdentityProfileResolution(profile=self.profile, created=False)

    def local_identity(self, *, user_id: int) -> LocalIdentity | None:
        return self.local if user_id == 7 else None

    def set_blocked(self, *, user_id: int, blocked: bool) -> str | None:
        raise AssertionError("not used")


def test_cloud_and_access_key_identity_paths_share_account_rules() -> None:
    gateway = _IdentityGateway()
    identity = Identity(gateway, journal=MagicMock(spec=OperationJournal))
    cloud_actor = identity.resolve_actor(
        AuthenticatedIdentity(
            id=7,
            email="reader@example.com",
            display_name="Reader",
            status="active",
            email_verified=True,
        ),
        operation=_operation(),
    )
    local_actor = identity.resolve_actor_by_user_id(7)

    assert local_actor == cloud_actor

    for unavailable in (
        Identity(
            _IdentityGateway(status="pending"),
            journal=MagicMock(spec=OperationJournal),
        ),
        Identity(
            _IdentityGateway(blocked=True),
            journal=MagicMock(spec=OperationJournal),
        ),
    ):
        with pytest.raises(AppError):
            unavailable.resolve_actor_by_user_id(7)
