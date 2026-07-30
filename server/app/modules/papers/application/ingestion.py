"""One PDF-ingestion use case shared by HTTP, Agent, and future MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.papers.domain import normalize_idempotency_key
from app.modules.jobs.application.actions import JOB_COMPLETED, JOB_CREATED, JOB_FAILED
from app.modules.papers.application.actions import (
    DOCUMENT_PROCESSING_FAILED,
    LIBRARY_PAPER_REMOVED,
)
from app.modules.projects.application.actions import PROJECT_PAPER_REMOVED
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)
from app.shared.application import Actor, OperationContext

PAPER_INGESTED = OperationAction("paper.ingested")


@dataclass(frozen=True, slots=True)
class FetchedPdf:
    content: bytes
    filename: str


@dataclass(frozen=True, slots=True)
class IngestionReservation:
    job_id: UUID
    replayed: bool
    reaped_stale_uploads: tuple[ReapedStaleIngestion, ...] = ()


@dataclass(frozen=True, slots=True)
class ReapedStaleIngestion:
    job_id: UUID
    document_id: UUID | None
    project_id: UUID | None
    reference_removed: bool
    document_processing_failed: bool
    created_gc_job_id: UUID | None


@dataclass(frozen=True, slots=True)
class IngestionFinalization:
    task_id: str
    job_id: UUID
    document_id: UUID
    project_id: UUID | None
    changed: bool
    job_completed: bool


@dataclass(frozen=True, slots=True)
class PreparedPaperInput:
    content: bytes
    filename: str | None


class PdfInputValidator(Protocol):
    def validate(self, *, content: bytes, source: str) -> None: ...


class PdfUrlSource(Protocol):
    async def fetch(self, *, url: str) -> FetchedPdf: ...


class PaperIngestionLimits(Protocol):
    async def enforce_rate(
        self,
        *,
        actor: Actor,
        ip_address: str,
    ) -> None: ...

    async def acquire(self, *, actor: Actor, job_id: UUID) -> None: ...

    async def release(self, *, actor: Actor, job_id: UUID) -> None: ...


class PaperIngestionGateway(Protocol):
    def reserve(
        self,
        *,
        actor: Actor,
        correlation_id: UUID,
        origin_operation_id: UUID,
        project_id: UUID | None,
        content: bytes,
        filename: str | None,
        idempotency_key: str | None,
    ) -> IngestionReservation: ...

    def fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> bool: ...

    def finalize(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        content: bytes,
    ) -> IngestionFinalization: ...


class IngestPaper:
    def __init__(
        self,
        *,
        validator: PdfInputValidator,
        limits: PaperIngestionLimits,
        gateway: PaperIngestionGateway,
        journal: OperationJournal,
    ) -> None:
        self._validator = validator
        self._limits = limits
        self._gateway = gateway
        self._journal = journal

    async def prepare_bytes(
        self,
        *,
        actor: Actor,
        content: bytes,
        filename: str | None,
        ip_address: str,
    ) -> PreparedPaperInput:
        await self._limits.enforce_rate(actor=actor, ip_address=ip_address)
        self._validator.validate(content=content, source=filename or "upload")
        return PreparedPaperInput(content=content, filename=filename)

    async def prepare_url(
        self,
        *,
        actor: Actor,
        url: str,
        source: PdfUrlSource,
        ip_address: str,
    ) -> PreparedPaperInput:
        await self._limits.enforce_rate(actor=actor, ip_address=ip_address)
        fetched = await source.fetch(url=url)
        self._validator.validate(content=fetched.content, source=fetched.filename)
        return PreparedPaperInput(
            content=fetched.content,
            filename=fetched.filename,
        )

    def reserve(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedPaperInput,
        project_id: UUID | None,
        idempotency_key: str | None,
    ) -> IngestionReservation:
        reservation = self._gateway.reserve(
            actor=actor,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            project_id=project_id,
            content=prepared.content,
            filename=prepared.filename,
            idempotency_key=normalize_idempotency_key(idempotency_key),
        )
        changes: list[OperationChange] = []
        for reaped in reservation.reaped_stale_uploads:
            changes.append(
                OperationChange(
                    action=JOB_FAILED,
                    resources=(ResourceRef("job", str(reaped.job_id)),),
                )
            )
            if reaped.document_id is not None:
                if reaped.document_processing_failed:
                    changes.append(
                        OperationChange(
                            action=DOCUMENT_PROCESSING_FAILED,
                            resources=(
                                ResourceRef("document", str(reaped.document_id)),
                            ),
                        )
                    )
                if reaped.reference_removed:
                    resources = [ResourceRef("document", str(reaped.document_id))]
                    if reaped.project_id is None:
                        action = LIBRARY_PAPER_REMOVED
                    else:
                        action = PROJECT_PAPER_REMOVED
                        resources.append(ResourceRef("project", str(reaped.project_id)))
                    changes.append(
                        OperationChange(action=action, resources=tuple(resources))
                    )
            if reaped.created_gc_job_id is not None:
                changes.append(
                    OperationChange(
                        action=JOB_CREATED,
                        resources=(ResourceRef("job", str(reaped.created_gc_job_id)),),
                    )
                )
        if not reservation.replayed:
            changes.append(
                OperationChange(
                    action=JOB_CREATED,
                    resources=(ResourceRef("job", str(reservation.job_id)),),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )
        return reservation

    async def acquire(self, *, actor: Actor, job_id: UUID) -> None:
        await self._limits.acquire(actor=actor, job_id=job_id)

    async def release(self, *, actor: Actor, job_id: UUID) -> None:
        await self._limits.release(actor=actor, job_id=job_id)

    def finalize(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        prepared: PreparedPaperInput,
    ) -> IngestionFinalization:
        result = self._gateway.finalize(
            actor=actor,
            job_id=job_id,
            content=prepared.content,
        )
        changes: list[OperationChange] = []
        if result.changed:
            resources = [
                ResourceRef("document", str(result.document_id)),
                ResourceRef("job", str(result.job_id)),
            ]
            if result.project_id is not None:
                resources.append(ResourceRef("project", str(result.project_id)))
            changes.append(
                OperationChange(
                    action=PAPER_INGESTED,
                    resources=tuple(resources),
                )
            )
        if result.job_completed:
            changes.append(
                OperationChange(
                    action=JOB_COMPLETED,
                    resources=(ResourceRef("job", str(result.job_id)),),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )
        return result

    def fail(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        error_code: str,
    ) -> None:
        changed = self._gateway.fail(
            actor=actor,
            job_id=job_id,
            error_code=error_code,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_FAILED,
                resources=(ResourceRef(type="job", id=str(job_id)),),
            )
