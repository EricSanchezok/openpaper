"""One PDF-ingestion use case shared by HTTP, Agent, and future MCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.papers.domain import normalize_idempotency_key
from app.shared.application import Actor


@dataclass(frozen=True, slots=True)
class FetchedPdf:
    content: bytes
    filename: str


@dataclass(frozen=True, slots=True)
class IngestionReservation:
    job_id: UUID
    replayed: bool


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
        project_id: UUID | None,
        content: bytes,
        filename: str | None,
        idempotency_key: str | None,
    ) -> IngestionReservation: ...

    def fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> None: ...

    def finalize(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        content: bytes,
    ) -> str: ...


class IngestPaper:
    def __init__(
        self,
        *,
        validator: PdfInputValidator,
        limits: PaperIngestionLimits,
        gateway: PaperIngestionGateway,
    ) -> None:
        self._validator = validator
        self._limits = limits
        self._gateway = gateway

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
        prepared: PreparedPaperInput,
        project_id: UUID | None,
        idempotency_key: str | None,
    ) -> IngestionReservation:
        return self._gateway.reserve(
            actor=actor,
            project_id=project_id,
            content=prepared.content,
            filename=prepared.filename,
            idempotency_key=normalize_idempotency_key(idempotency_key),
        )

    async def acquire(self, *, actor: Actor, job_id: UUID) -> None:
        await self._limits.acquire(actor=actor, job_id=job_id)

    async def release(self, *, actor: Actor, job_id: UUID) -> None:
        await self._limits.release(actor=actor, job_id=job_id)

    def finalize(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        prepared: PreparedPaperInput,
    ) -> str:
        return self._gateway.finalize(
            actor=actor,
            job_id=job_id,
            content=prepared.content,
        )

    def fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> None:
        self._gateway.fail(actor=actor, job_id=job_id, error_code=error_code)
