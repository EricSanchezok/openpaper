"""Concrete persistence and operation handlers for generic Jobs callbacks."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from app.modules.jobs.application.callbacks import JobCompletionHandler
from app.modules.jobs.application.contracts import (
    AudioOverviewWebhookData,
    DataTableWebhookData,
    JobCallbackIdentity,
    PdfProcessingWebhookData,
    StorageDeleteCallback,
)
from app.modules.jobs.infrastructure import (
    document_callbacks,
    research_callbacks,
)
from app.modules.jobs.infrastructure.repository import job_repository
from app.shared.domain.enums import JobOperation
from pydantic import BaseModel
from sqlalchemy.orm import Session


class SqlAlchemyJobLifecycle:
    def __init__(self, db: Session) -> None:
        self._db = db

    def operation(self, *, job_id: UUID) -> JobOperation:
        return JobOperation(job_repository.require(self._db, job_id=job_id).operation)

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

    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object:
        return await document_callbacks.handle_paper_processing_webhook(
            str(job_id),
            cast(PdfProcessingWebhookData, callback),
            self._db,
        )


class PdfPostprocessCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object:
        return document_callbacks.complete_pdf_postprocess_job(
            job_id, cast(JobCallbackIdentity, callback), self._db
        )


class DocumentGcCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object:
        return document_callbacks.complete_document_gc_job(
            job_id, cast(JobCallbackIdentity, callback), self._db
        )


class StorageDeleteCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object:
        return document_callbacks.complete_storage_delete_job(
            job_id, cast(StorageDeleteCallback, callback), self._db
        )


class ZoteroPostprocessCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object:
        return await document_callbacks.complete_zotero_postprocess_job(
            job_id, cast(JobCallbackIdentity, callback), self._db
        )


class AudioCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object:
        return await research_callbacks.complete_audio_job(
            job_id, cast(AudioOverviewWebhookData, callback), self._db
        )


class DataTableCompletion(JobCompletionHandler):
    def __init__(self, db: Session) -> None:
        self._db = db

    async def complete(self, *, job_id: UUID, callback: BaseModel) -> object:
        return await research_callbacks.complete_data_table_job(
            job_id, cast(DataTableWebhookData, callback), self._db
        )


class ZoteroSyncSchedule:
    def __init__(self, db: Session) -> None:
        self._db = db

    def schedule_zotero_sync(self, *, threshold_seconds: int) -> dict[str, int]:
        return document_callbacks.schedule_zotero_jobs(
            threshold_seconds=threshold_seconds,
            db=self._db,
        )
