"""Database-free external discovery with short persistence boundaries."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.papers.application.contracts.discovery import (
    DiscoveryPaperListResponse,
    OpenAlexCitationGraph,
)
from app.modules.papers.application.discovery import ExternalPaperDiscovery
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)


class PaperDiscoveryWorkflow:
    """Orchestrate external catalog calls without an open application UoW."""

    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        external: ExternalPaperDiscovery,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._external = external
        self._operation_factory = operation_factory

    async def search(
        self,
        *,
        actor: Actor,
        client_ip: str,
        query: str,
        cursor: str | None,
    ) -> DiscoveryPaperListResponse:
        preparation = self._external.prepare_search(
            actor=actor,
            query=query,
            cursor=cursor,
        )
        return await self._external.search(
            actor=actor,
            client_ip=client_ip,
            preparation=preparation,
        )

    async def author_works(
        self,
        *,
        actor: Actor,
        client_ip: str,
        author_id: str,
        cursor: str | None,
    ) -> DiscoveryPaperListResponse:
        preparation = self._external.prepare_author_works(
            actor=actor,
            author_id=author_id,
            cursor=cursor,
        )
        return await self._external.author_works(
            actor=actor,
            client_ip=client_ip,
            preparation=preparation,
        )

    async def match(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        client_ip: str,
        doi: str | None,
        document_id: UUID | None,
    ) -> OpenAlexCitationGraph:
        preparation = self._executor.query(
            lambda capabilities: capabilities.paper_discovery.prepare_match(
                actor=actor,
                doi=doi,
                document_id=document_id,
            )
        )
        result = await self._external.fetch_match(
            actor=actor,
            client_ip=client_ip,
            preparation=preparation,
        )
        apply_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        graph = self._executor.command(
            lambda capabilities: capabilities.paper_discovery.complete_match(
                actor=actor,
                operation=apply_operation,
                preparation=preparation,
                result=result,
            )
        )
        self._external.record_match(actor=actor, result=result)
        return graph


__all__ = ["PaperDiscoveryWorkflow"]
