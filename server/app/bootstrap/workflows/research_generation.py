"""Short-transaction workflow for durable Research generation."""

from __future__ import annotations

from collections.abc import Callable

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.jobs.application.contracts import CreateJobResponse
from app.modules.research.application.generation import (
    GenerationCapacity,
    PreparedGeneration,
    ResearchGeneration,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)


class ResearchGenerationWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        capacity: GenerationCapacity,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._capacity = capacity
        self._operation_factory = operation_factory

    async def run(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        client_ip: str,
        prepare: Callable[
            [ResearchGeneration, OperationContext],
            CreateJobResponse | PreparedGeneration,
        ],
    ) -> CreateJobResponse:
        enqueue_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        prepared = self._executor.query(
            lambda capabilities: prepare(
                capabilities.research_generation,
                enqueue_operation,
            )
        )
        if isinstance(prepared, CreateJobResponse):
            return prepared

        await self._capacity.enforce_rate(
            actor=actor,
            client_ip=client_ip,
            feature=prepared.feature,
        )
        if prepared.feature == "audio":
            await self._capacity.acquire_audio(
                actor=actor,
                operation_id=prepared.command.job_id,
            )
        else:
            await self._capacity.acquire_background(
                actor=actor,
                operation_id=prepared.command.job_id,
            )

        try:
            response = self._executor.command(
                lambda capabilities: capabilities.research_generation.enqueue(
                    actor=actor,
                    operation=enqueue_operation,
                    prepared=prepared,
                )
            )
        except Exception:
            await self._release(actor=actor, prepared=prepared)
            raise

        if response.job.id != prepared.command.job_id:
            await self._release(actor=actor, prepared=prepared)
        return response

    async def _release(
        self,
        *,
        actor: Actor,
        prepared: PreparedGeneration,
    ) -> None:
        if prepared.feature == "audio":
            await self._capacity.release_audio(
                actor=actor,
                operation_id=prepared.command.job_id,
            )
        else:
            await self._capacity.release_background(
                actor=actor,
                operation_id=prepared.command.job_id,
            )
