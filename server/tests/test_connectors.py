from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app.modules.integrations.connectors.application.connectors import Connectors
from app.modules.integrations.connectors.application.ports import (
    ConnectorRecord,
    UnreadableConnectorCredential,
)
from app.modules.integrations.connectors.domain import ConnectorProvider
from app.modules.integrations.connectors.infrastructure.secrets import (
    AesGcmConnectorCredentialCipher,
)
from app.modules.operation_journal.application import OperationJournal
from app.shared.application import Actor, OperationContext

NOW = datetime(2026, 7, 31, 12, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _Gateway:
    def __init__(self) -> None:
        self.records: dict[tuple[int, ConnectorProvider], ConnectorRecord] = {}

    def list_owned(self, *, user_id: int) -> tuple[ConnectorRecord, ...]:
        return tuple(
            record
            for (owner_id, _), record in self.records.items()
            if owner_id == user_id
        )

    def get_owned(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        lock: bool = False,
    ) -> ConnectorRecord | None:
        del lock
        return self.records.get((user_id, provider))

    def upsert(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        credential_ciphertext: str,
        verified_at: datetime,
    ) -> ConnectorRecord:
        record = ConnectorRecord(
            user_id=user_id,
            provider=provider,
            credential_ciphertext=credential_ciphertext,
            enabled=True,
            verified_at=verified_at,
            created_at=verified_at,
            updated_at=verified_at,
        )
        self.records[(user_id, provider)] = record
        return record

    def set_enabled(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        enabled: bool,
        verified_at: datetime | None = None,
    ) -> ConnectorRecord:
        current = self.records[(user_id, provider)]
        record = replace(
            current,
            enabled=enabled,
            verified_at=verified_at or current.verified_at,
        )
        self.records[(user_id, provider)] = record
        return record

    def delete(self, *, user_id: int, provider: ConnectorProvider) -> None:
        self.records.pop((user_id, provider), None)


def _actor(user_id: int = 7) -> Actor:
    return Actor(
        id=user_id,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _cipher() -> AesGcmConnectorCredentialCipher:
    return AesGcmConnectorCredentialCipher(base64.urlsafe_b64encode(b"c" * 32).decode())


def _connectors(
    gateway: _Gateway,
    *,
    clock: _Clock | None = None,
) -> Connectors:
    return Connectors(
        gateway=gateway,
        cipher=_cipher(),
        clock=clock or _Clock(),
        journal=MagicMock(spec=OperationJournal),
        scholight_configured=True,
    )


def test_connector_lifecycle_keeps_credentials_server_side() -> None:
    gateway = _Gateway()
    connectors = _connectors(gateway)
    actor = _actor()
    operation = MagicMock(spec=OperationContext)

    initial = connectors.list(actor=actor)
    scholight = initial.items[0]
    assert (scholight.provider, scholight.built_in, scholight.enabled) == (
        ConnectorProvider.SCHOLIGHT,
        True,
        True,
    )

    connected = connectors.connect(
        actor=actor,
        operation=operation,
        provider=ConnectorProvider.EXA,
        api_key="private-api-key",
    )
    assert connected.connected is True
    assert connected.enabled is True
    assert "private-api-key" not in connected.model_dump_json()
    assert (
        connectors.credential(
            actor=actor,
            provider=ConnectorProvider.EXA,
        ).api_key
        == "private-api-key"
    )

    disabled = connectors.set_enabled(
        actor=actor,
        operation=operation,
        provider=ConnectorProvider.EXA,
        enabled=False,
    )
    assert disabled.enabled is False

    connectors.disconnect(
        actor=actor,
        operation=operation,
        provider=ConnectorProvider.EXA,
    )
    assert gateway.records == {}


def test_unreadable_enabled_credential_is_reported_without_exposing_ciphertext() -> (
    None
):
    gateway = _Gateway()
    gateway.records[(7, ConnectorProvider.TAVILY)] = ConnectorRecord(
        user_id=7,
        provider=ConnectorProvider.TAVILY,
        credential_ciphertext="v1.tampered",
        enabled=True,
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )

    states = _connectors(gateway).enabled_credentials(actor=_actor())

    assert states == (UnreadableConnectorCredential(ConnectorProvider.TAVILY),)


def test_successful_revalidation_refreshes_verified_at() -> None:
    gateway = _Gateway()
    actor = _actor()
    operation = MagicMock(spec=OperationContext)
    _connectors(gateway).connect(
        actor=actor,
        operation=operation,
        provider=ConnectorProvider.ANYSEARCH,
        api_key="private-api-key",
    )
    reverified_at = NOW + timedelta(days=1)

    result = _connectors(
        gateway,
        clock=_Clock(reverified_at),
    ).set_enabled(
        actor=actor,
        operation=operation,
        provider=ConnectorProvider.ANYSEARCH,
        enabled=True,
    )

    assert result.verified_at == reverified_at
