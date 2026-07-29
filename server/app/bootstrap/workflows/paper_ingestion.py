"""Prepare/external/finalize workflow for paper ingestion."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.telemetry import track_event
from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.uploads import UploadAcceptedResponse
from app.modules.papers.application.ingestion import PdfUrlSource, PreparedPaperInput
from app.modules.papers.domain import content_sha256
from app.shared.application import Actor, ApplicationExecutor
from app.shared.domain import AppError, FailureKind

logger = logging.getLogger(__name__)


class PaperIngestionWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        url_source: PdfUrlSource,
    ) -> None:
        self._executor = executor
        self._url_source = url_source

    async def from_url(
        self,
        *,
        actor: Actor,
        url: str,
        project_id: UUID | None,
        idempotency_key: str | None,
        ip_address: str,
    ) -> UploadAcceptedResponse:
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        prepared = await ingestion.prepare_url(
            actor=actor,
            url=url,
            source=self._url_source,
            ip_address=ip_address,
        )
        return await self._start(
            actor=actor,
            prepared=prepared,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

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
        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        prepared = await ingestion.prepare_bytes(
            actor=actor,
            content=content,
            filename=filename,
            ip_address=ip_address,
        )
        return await self._start(
            actor=actor,
            prepared=prepared,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def _start(
        self,
        *,
        actor: Actor,
        prepared: PreparedPaperInput,
        project_id: UUID | None,
        idempotency_key: str | None,
    ) -> UploadAcceptedResponse:
        reservation = self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.reserve(
                actor=actor,
                prepared=prepared,
                project_id=project_id,
                idempotency_key=idempotency_key,
            )
        )
        if reservation.replayed:
            return UploadAcceptedResponse(job_id=reservation.job_id)

        ingestion = self._executor.query(
            lambda capabilities: capabilities.paper_ingestion
        )
        try:
            await ingestion.acquire(actor=actor, job_id=reservation.job_id)
            digest = content_sha256(prepared.content)
            await asyncio.to_thread(
                s3_service.upload_document_source,
                sha256=digest,
                pdf_bytes=prepared.content,
            )
            task_id = self._executor.command(
                lambda capabilities: capabilities.paper_ingestion.finalize(
                    actor=actor,
                    job_id=reservation.job_id,
                    prepared=prepared,
                )
            )
            if task_id.startswith("reused:") or task_id != str(reservation.job_id):
                await ingestion.release(actor=actor, job_id=reservation.job_id)
            track_event(
                "paper_upload_submitted_to_microservice",
                properties={"task_id": task_id},
                user_id=str(actor.id),
            )
            return UploadAcceptedResponse(job_id=reservation.job_id)
        except AppError as exc:
            self._fail(actor=actor, job_id=reservation.job_id, error_code=exc.code)
            await ingestion.release(actor=actor, job_id=reservation.job_id)
            raise
        except Exception as exc:
            logger.error("Document processing job submission failed", exc_info=True)
            self._fail(
                actor=actor,
                job_id=reservation.job_id,
                error_code="jobs_submission_failed",
            )
            await ingestion.release(actor=actor, job_id=reservation.job_id)
            raise AppError(
                code="jobs_submission_failed",
                message="The document processing job could not be started",
                kind=FailureKind.UNAVAILABLE,
            ) from exc

    def _fail(self, *, actor: Actor, job_id: UUID, error_code: str) -> None:
        self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.fail(
                actor=actor,
                job_id=job_id,
                error_code=error_code,
            )
        )
