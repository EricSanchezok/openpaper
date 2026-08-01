"""Prepare/external/finalize workflow for paper ingestion."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.product_analytics import track_event
from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.uploads import UploadAcceptedResponse
from app.modules.papers.application.ingestion import PdfUrlSource, PreparedPaperInput
from app.modules.papers.domain import content_sha256
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import AppError, FailureKind

logger = logging.getLogger(__name__)


class PaperIngestionWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        url_source: PdfUrlSource,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._url_source = url_source
        self._operation_factory = operation_factory

    async def from_url(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
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
            operation=operation,
            prepared=prepared,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def from_bytes(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
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
            operation=operation,
            prepared=prepared,
            project_id=project_id,
            idempotency_key=idempotency_key,
        )

    async def _start(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedPaperInput,
        project_id: UUID | None,
        idempotency_key: str | None,
    ) -> UploadAcceptedResponse:
        reserve_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        reservation = self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.reserve(
                actor=actor,
                operation=reserve_operation,
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
            finalize_operation = self._operation_factory.child(
                reserve_operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            finalization = self._executor.command(
                lambda capabilities: capabilities.paper_ingestion.finalize(
                    actor=actor,
                    operation=finalize_operation,
                    job_id=reservation.job_id,
                    prepared=prepared,
                )
            )
            if finalization.job_completed:
                await ingestion.release(actor=actor, job_id=reservation.job_id)
            track_event(
                "paper_upload_submitted_to_microservice",
                properties={"task_id": finalization.task_id},
                user_id=str(actor.id),
            )
            return UploadAcceptedResponse(job_id=reservation.job_id)
        except AppError as exc:
            self._fail(
                actor=actor,
                operation=reserve_operation,
                job_id=reservation.job_id,
                error_code=exc.code,
            )
            await ingestion.release(actor=actor, job_id=reservation.job_id)
            raise
        except Exception as exc:
            logger.error("paper_ingestion.job_submission.failed", exc_info=True)
            self._fail(
                actor=actor,
                operation=reserve_operation,
                job_id=reservation.job_id,
                error_code="jobs_submission_failed",
            )
            await ingestion.release(actor=actor, job_id=reservation.job_id)
            raise AppError(
                code="jobs_submission_failed",
                message="The document processing job could not be started",
                kind=FailureKind.UNAVAILABLE,
            ) from exc

    def _fail(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        error_code: str,
    ) -> None:
        fail_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        self._executor.command(
            lambda capabilities: capabilities.paper_ingestion.fail(
                actor=actor,
                operation=fail_operation,
                job_id=job_id,
                error_code=error_code,
            )
        )
