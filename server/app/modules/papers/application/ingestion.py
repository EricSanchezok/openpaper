"""One PDF-ingestion use case shared by HTTP, Agent, and future MCP."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.papers.application.contracts.uploads import UploadAcceptedResponse
from app.shared.application import Actor
from app.shared.domain import AppError

MAX_PDF_SIZE_MB = 30
MAX_PDF_BYTES = MAX_PDF_SIZE_MB * 1024 * 1024


@dataclass(frozen=True, slots=True)
class FetchedPdf:
    content: bytes
    filename: str


@dataclass(frozen=True, slots=True)
class IngestionReservation:
    job_id: UUID
    replayed: bool


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

    async def dispatch(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        content: bytes,
    ) -> None: ...


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

    async def from_bytes(
        self,
        *,
        actor: Actor,
        content: bytes,
        filename: str | None,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> UploadAcceptedResponse:
        await self._limits.enforce_rate(actor=actor, ip_address=ip_address)
        return await self._start(
            actor=actor,
            content=content,
            filename=filename,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def from_url(
        self,
        *,
        actor: Actor,
        url: str,
        source: PdfUrlSource,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> UploadAcceptedResponse:
        await self._limits.enforce_rate(actor=actor, ip_address=ip_address)
        fetched = await source.fetch(url=url)
        return await self._start(
            actor=actor,
            content=fetched.content,
            filename=fetched.filename,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def _start(
        self,
        *,
        actor: Actor,
        content: bytes,
        filename: str | None,
        project_id: UUID | None,
        idempotency_key: str | None,
    ) -> UploadAcceptedResponse:
        self._validator.validate(content=content, source=filename or "upload")
        reservation = self._gateway.reserve(
            actor=actor,
            project_id=project_id,
            content=content,
            filename=filename,
            idempotency_key=_normalize_idempotency_key(idempotency_key),
        )
        if reservation.replayed:
            return UploadAcceptedResponse(job_id=reservation.job_id)
        try:
            await self._limits.acquire(actor=actor, job_id=reservation.job_id)
        except AppError as exc:
            self._gateway.fail(
                actor=actor,
                job_id=reservation.job_id,
                error_code=exc.code,
            )
            raise
        await self._gateway.dispatch(
            actor=actor,
            job_id=reservation.job_id,
            content=content,
        )
        return UploadAcceptedResponse(job_id=reservation.job_id)


def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        raise AppError(
            code="invalid_idempotency_key",
            message="Idempotency-Key must contain between 1 and 200 characters",
            status_code=400,
        )
    return normalized
