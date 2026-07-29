"""Cross-module infrastructure adapter for paper ingestion."""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
from uuid import UUID

from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
)
from app.helpers.parser import validate_pdf_content, validate_url_and_fetch_pdf
from app.helpers.ai_limits import release_concurrency_by_id
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.papers.application.ingestion import (
    FetchedPdf,
    IngestionReservation,
)
from app.modules.papers.domain import content_sha256, durable_ingestion_key
from app.bootstrap.adapters.document_submission import finalize_reserved_document
from app.bootstrap.adapters.upload_repository import (
    upload_reservation_repository,
)
from app.bootstrap.adapters.upload_reservations import reserve_upload
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from sqlalchemy.orm import Session


class DefaultPdfInputValidator:
    def validate(self, *, content: bytes, source: str) -> None:
        valid, error = validate_pdf_content(content, source)
        if not valid:
            raise AppError(
                code="invalid_pdf",
                message=error or "The uploaded file is not a valid PDF",
                kind=FailureKind.INVALID_ARGUMENT,
            )


class SafePdfUrlSource:
    async def fetch(self, *, url: str) -> FetchedPdf:
        valid, content, error = await asyncio.to_thread(
            validate_url_and_fetch_pdf,
            url,
        )
        if not valid:
            raise AppError(
                code="invalid_pdf_url",
                message=error or "The URL did not return a valid PDF",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        filename = (
            PurePosixPath(unquote(urlparse(url).path)).name or "downloaded-paper.pdf"
        )
        return FetchedPdf(content=content, filename=filename)


class DefaultPaperIngestionLimits:
    async def enforce_rate(
        self,
        *,
        actor: Actor,
        ip_address: str,
    ) -> None:
        try:
            await enforce_rate_limit(
                user_id=actor.id,
                ip_address=ip_address,
                feature="upload",
            )
        except AILimitExceeded as exc:
            raise AppError(
                code=exc.code,
                message="Upload rate limit exceeded",
                kind=FailureKind.RATE_LIMITED,
            ) from None

    async def acquire(self, *, actor: Actor, job_id: UUID) -> None:
        try:
            await acquire_concurrency(
                user_id=actor.id,
                category="background",
                operation_id=str(job_id),
            )
        except AILimitExceeded as exc:
            raise AppError(
                code=exc.code,
                message="Too many background jobs are already running",
                kind=FailureKind.RATE_LIMITED,
            ) from None

    async def release(self, *, actor: Actor, job_id: UUID) -> None:
        await release_concurrency_by_id(
            user_id=actor.id,
            category="background",
            operation_id=str(job_id),
        )


class SqlPaperIngestionGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def reserve(
        self,
        *,
        actor: Actor,
        project_id: UUID | None,
        content: bytes,
        filename: str | None,
        idempotency_key: str | None,
    ) -> IngestionReservation:
        durable_key = durable_ingestion_key(
            actor_id=actor.id,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )
        replayed = (
            durable_key is not None
            and job_repository.find_by_idempotency_key(
                self._db,
                idempotency_key=durable_key,
            )
            is not None
        )
        reservation = reserve_upload(
            self._db,
            requester=actor,
            project_id=project_id,
            input_size_bytes=len(content),
            original_filename=filename,
            content_sha256=content_sha256(content),
            idempotency_key=idempotency_key,
        )
        replayed = (
            replayed
            or reservation.job.dispatch is not None
            or reservation.job.document_id is not None
        )
        return IngestionReservation(job_id=reservation.id, replayed=replayed)

    def fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> None:
        upload_reservation_repository.mark_as_failed(
            db=self._db,
            job_id=str(job_id),
            user=actor,
            error_code=error_code,
        )

    def finalize(
        self,
        *,
        actor: Actor,
        job_id: UUID,
        content: bytes,
    ) -> str:
        reservation = upload_reservation_repository.get(
            self._db,
            id=job_id,
            user=actor,
        )
        if reservation is None:
            raise RuntimeError("reserved_ingestion_not_found")
        return finalize_reserved_document(
            pdf_bytes=content,
            upload_job=reservation,
            user=actor,
            db=self._db,
        )
