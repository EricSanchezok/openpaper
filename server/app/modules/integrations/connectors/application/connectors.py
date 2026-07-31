"""User-owned connector connection use cases."""

from __future__ import annotations

from datetime import datetime

from app.modules.integrations.connectors.application.contracts import (
    ConnectorListResponse,
    ConnectorResponse,
)
from app.modules.integrations.connectors.application.ports import (
    ConnectorCredential,
    ConnectorCredentialState,
    ConnectorCredentialCipher,
    ConnectorGateway,
    UnreadableConnectorCredential,
)
from app.modules.integrations.connectors.domain import (
    EXTERNAL_CONNECTOR_PROVIDERS,
    ConnectorProvider,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, Clock, OperationContext
from app.shared.domain import AppError, FailureKind

CONNECTOR_CONNECTED = OperationAction("connector.connected")
CONNECTOR_ENABLED = OperationAction("connector.enabled")
CONNECTOR_DISABLED = OperationAction("connector.disabled")
CONNECTOR_DISCONNECTED = OperationAction("connector.disconnected")

_DISPLAY_NAMES = {
    ConnectorProvider.SCHOLIGHT: "Scholight",
    ConnectorProvider.ANYSEARCH: "AnySearch",
    ConnectorProvider.TAVILY: "Tavily",
    ConnectorProvider.EXA: "Exa",
    ConnectorProvider.FIRECRAWL: "Firecrawl",
}


class Connectors:
    def __init__(
        self,
        *,
        gateway: ConnectorGateway,
        cipher: ConnectorCredentialCipher,
        clock: Clock,
        journal: OperationJournal,
        scholight_configured: bool,
    ) -> None:
        self._gateway = gateway
        self._cipher = cipher
        self._clock = clock
        self._journal = journal
        self._scholight_configured = scholight_configured

    def list(self, *, actor: Actor) -> ConnectorListResponse:
        records = {
            record.provider: record
            for record in self._gateway.list_owned(user_id=actor.id)
        }
        items = [
            ConnectorResponse(
                provider=ConnectorProvider.SCHOLIGHT,
                display_name=_DISPLAY_NAMES[ConnectorProvider.SCHOLIGHT],
                built_in=True,
                connected=self._scholight_configured,
                enabled=self._scholight_configured,
            )
        ]
        for provider in EXTERNAL_CONNECTOR_PROVIDERS:
            record = records.get(provider)
            items.append(
                ConnectorResponse(
                    provider=provider,
                    display_name=_DISPLAY_NAMES[provider],
                    built_in=False,
                    connected=record is not None,
                    enabled=record.enabled if record is not None else False,
                    verified_at=record.verified_at if record is not None else None,
                )
            )
        return ConnectorListResponse(items=items)

    def connect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: ConnectorProvider,
        api_key: str,
    ) -> ConnectorResponse:
        _require_external(provider)
        now = self._clock.now()
        record = self._gateway.upsert(
            user_id=actor.id,
            provider=provider,
            credential_ciphertext=self._cipher.encrypt(
                user_id=actor.id,
                provider=provider,
                plaintext=api_key,
            ),
            verified_at=now,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONNECTOR_CONNECTED,
            resources=(ResourceRef("connector", provider.value),),
        )
        return _response(record.provider, record.enabled, record.verified_at)

    def set_enabled(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: ConnectorProvider,
        enabled: bool,
    ) -> ConnectorResponse:
        _require_external(provider)
        current = self._gateway.get_owned(
            user_id=actor.id,
            provider=provider,
            lock=True,
        )
        if current is None:
            raise AppError(
                code="connector_not_connected",
                message="Connector is not connected",
                kind=FailureKind.CONFLICT,
            )
        if current.enabled == enabled:
            return _response(provider, current.enabled, current.verified_at)
        updated = self._gateway.set_enabled(
            user_id=actor.id,
            provider=provider,
            enabled=enabled,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONNECTOR_ENABLED if enabled else CONNECTOR_DISABLED,
            resources=(ResourceRef("connector", provider.value),),
        )
        return _response(provider, updated.enabled, updated.verified_at)

    def disconnect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: ConnectorProvider,
    ) -> None:
        _require_external(provider)
        current = self._gateway.get_owned(
            user_id=actor.id,
            provider=provider,
            lock=True,
        )
        if current is None:
            return
        self._gateway.delete(user_id=actor.id, provider=provider)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=CONNECTOR_DISCONNECTED,
            resources=(ResourceRef("connector", provider.value),),
        )

    def credential(
        self,
        *,
        actor: Actor,
        provider: ConnectorProvider,
        require_enabled: bool = True,
    ) -> ConnectorCredential:
        _require_external(provider)
        record = self._gateway.get_owned(
            user_id=actor.id,
            provider=provider,
        )
        if record is None or (require_enabled and not record.enabled):
            raise AppError(
                code="connector_not_connected",
                message="Connector is not connected and enabled",
                kind=FailureKind.CONFLICT,
            )
        try:
            api_key = self._cipher.decrypt(
                user_id=actor.id,
                provider=provider,
                ciphertext=record.credential_ciphertext,
            )
        except ValueError as exc:
            raise AppError(
                code="connector_credentials_unreadable",
                message="Connector credentials could not be read; reconnect the connector",
                kind=FailureKind.UNAVAILABLE,
            ) from exc
        return ConnectorCredential(
            provider=provider,
            api_key=api_key,
            updated_at=record.updated_at,
        )

    def enabled_credentials(
        self,
        *,
        actor: Actor,
    ) -> tuple[ConnectorCredentialState, ...]:
        result: list[ConnectorCredentialState] = []
        for record in self._gateway.list_owned(user_id=actor.id):
            if not record.enabled:
                continue
            try:
                api_key = self._cipher.decrypt(
                    user_id=actor.id,
                    provider=record.provider,
                    ciphertext=record.credential_ciphertext,
                )
            except ValueError:
                result.append(UnreadableConnectorCredential(record.provider))
                continue
            result.append(
                ConnectorCredential(
                    provider=record.provider,
                    api_key=api_key,
                    updated_at=record.updated_at,
                )
            )
        return tuple(result)


def _require_external(provider: ConnectorProvider) -> None:
    if provider is ConnectorProvider.SCHOLIGHT:
        raise AppError(
            code="connector_managed_by_system",
            message="Scholight is managed by Scholens",
            kind=FailureKind.CONFLICT,
        )
    if provider not in EXTERNAL_CONNECTOR_PROVIDERS:
        raise AppError(
            code="connector_not_supported",
            message="Connector provider is not supported",
            kind=FailureKind.NOT_FOUND,
        )


def _response(
    provider: ConnectorProvider,
    enabled: bool,
    verified_at: datetime,
) -> ConnectorResponse:
    return ConnectorResponse(
        provider=provider,
        display_name=_DISPLAY_NAMES[provider],
        built_in=False,
        connected=True,
        enabled=enabled,
        verified_at=verified_at,
    )
