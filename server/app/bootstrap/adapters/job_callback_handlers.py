"""Concrete persistence and operation handlers for generic Jobs callbacks."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from app.modules.jobs.application.callbacks import (
    JobCompletionHandler,
    JobHandlerResult,
    PdfPostprocessResolution,
    ScheduledZoteroJobs,
)
from app.modules.jobs.application.contracts import (
    AudioOverviewWebhookData,
    DataTableWebhookData,
    JobCallbackIdentity,
    PdfProcessingWebhookData,
    StorageDeleteCallback,
)
from app.bootstrap.adapters import document_job_callbacks
from app.modules.jobs.infrastructure import research_callbacks
from app.modules.jobs.infrastructure.repository import job_repository
from app.shared.application import Actor, OperationContext
from app.shared.domain.enums import JobOperation, JobStatus
from pydantic import BaseModel
from sqlalchemy.orm import Session


class SqlAlchemyJobLifecycle:
    def __init__(self, db: Session) -> None:
        self._db = db

    def operation(self, *, job_id: UUID) -> JobOperation:
        return JobOperation(job_repository.require(self._db, job_id=job_id).operation)

    def status(self, *, job_id: UUID) -> JobStatus:
        return JobStatus(job_repository.require(self._db, job_id=job_id).status)

    def claim(self, *, job_id: UUID) -> bool:
        return job_repository.claim(self._db, job_id=job_id) is not None

    def heartbeat(self, *, job_id: UUID) -> bool:
        return job_repository.heartbeat(self._db, job_id=job_id)

    def fail(self, *, job_id: UUID, error_code: str) -> bool:
        _job, changed = job_repository.fail(
            self._db, job_id=job_id, error_code=error_code
        )
        return changed


class PdfProcessCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        if actor is None:
            raise RuntimeError("pdf_process_job_owner_missing")
        return await document_job_callbacks.handle_paper_processing_webhook(
            str(job_id),
            cast(PdfProcessingWebhookData, callback),
            self._db,
            actor=actor,
            operation=operation,
        )


class PdfPostprocessCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        raise RuntimeError("pdf_postprocess_requires_external_resolution")

    async def complete_resolved(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
        resolution: PdfPostprocessResolution,
    ) -> JobHandlerResult:
        return document_job_callbacks.complete_pdf_postprocess_job(
            job_id,
            cast(JobCallbackIdentity, callback),
            self._db,
            actor=actor,
            operation=operation,
            resolution=resolution,
        )


class DocumentGcCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        return document_job_callbacks.complete_document_gc_job(
            job_id,
            cast(JobCallbackIdentity, callback),
            self._db,
            operation=operation,
        )


class StorageDeleteCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        return document_job_callbacks.complete_storage_delete_job(
            job_id, cast(StorageDeleteCallback, callback), self._db
        )


class AudioCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        return await research_callbacks.complete_audio_job(
            job_id, cast(AudioOverviewWebhookData, callback), self._db
        )


class DataTableCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        return await research_callbacks.complete_data_table_job(
            job_id, cast(DataTableWebhookData, callback), self._db
        )


class ZoteroSyncSchedule:
    def __init__(self, db: Session) -> None:
        self._db = db

    def schedule_zotero_sync(
        self,
        *,
        threshold_seconds: int,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> ScheduledZoteroJobs:
        return document_job_callbacks.schedule_zotero_jobs(
            threshold_seconds=threshold_seconds,
            db=self._db,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
        )
