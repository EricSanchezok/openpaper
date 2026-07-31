"""External validation followed by short Connector persistence commands."""

from __future__ import annotations

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.integrations.connectors.application.contracts import (
    ConnectorListResponse,
    ConnectorResponse,
)
from app.modules.integrations.connectors.domain import ConnectorProvider
from app.modules.integrations.connectors.infrastructure.mcp import ConnectorToolResolver
from app.shared.application import Actor, ApplicationExecutor, OperationContext


class ConnectorWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        resolver: ConnectorToolResolver,
    ) -> None:
        self._executor = executor
        self._resolver = resolver

    def list(self, *, actor: Actor) -> ConnectorListResponse:
        return self._executor.query(
            lambda capabilities: capabilities.connectors.list(actor=actor)
        )

    async def connect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: ConnectorProvider,
        api_key: str,
    ) -> ConnectorResponse:
        await self._resolver.probe(provider=provider, api_key=api_key)
        return self._executor.command(
            lambda capabilities: capabilities.connectors.connect(
                actor=actor,
                operation=operation,
                provider=provider,
                api_key=api_key,
            )
        )

    async def set_enabled(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: ConnectorProvider,
        enabled: bool,
    ) -> ConnectorResponse:
        if enabled:
            credential = self._executor.query(
                lambda capabilities: capabilities.connectors.credential(
                    actor=actor,
                    provider=provider,
                    require_enabled=False,
                )
            )
            await self._resolver.probe(
                provider=provider,
                api_key=credential.api_key,
            )
        return self._executor.command(
            lambda capabilities: capabilities.connectors.set_enabled(
                actor=actor,
                operation=operation,
                provider=provider,
                enabled=enabled,
            )
        )

    def disconnect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        provider: ConnectorProvider,
    ) -> None:
        self._executor.command(
            lambda capabilities: capabilities.connectors.disconnect(
                actor=actor,
                operation=operation,
                provider=provider,
            )
        )
