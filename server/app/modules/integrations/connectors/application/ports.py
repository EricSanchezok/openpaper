"""Ports and immutable snapshots for user-owned connector connections."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.modules.integrations.connectors.domain import ConnectorProvider


@dataclass(frozen=True, slots=True)
class ConnectorRecord:
    user_id: int
    provider: ConnectorProvider
    credential_ciphertext: str = field(repr=False)
    enabled: bool
    verified_at: datetime
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectorCredential:
    provider: ConnectorProvider
    api_key: str = field(repr=False)
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UnreadableConnectorCredential:
    provider: ConnectorProvider
    code: str = "connector_credentials_unreadable"


ConnectorCredentialState = ConnectorCredential | UnreadableConnectorCredential


class ConnectorGateway(Protocol):
    def list_owned(self, *, user_id: int) -> tuple[ConnectorRecord, ...]: ...

    def get_owned(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        lock: bool = False,
    ) -> ConnectorRecord | None: ...

    def upsert(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        credential_ciphertext: str,
        verified_at: datetime,
    ) -> ConnectorRecord: ...

    def set_enabled(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        enabled: bool,
    ) -> ConnectorRecord: ...

    def delete(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
    ) -> None: ...


class ConnectorCredentialCipher(Protocol):
    def encrypt(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        plaintext: str,
    ) -> str: ...

    def decrypt(
        self,
        *,
        user_id: int,
        provider: ConnectorProvider,
        ciphertext: str,
    ) -> str: ...
