"""Signed webhook handlers for Scholens Jobs service integrations."""

import logging
import uuid
from datetime import datetime, timezone

from app.database.crud.message_crud import MessageCreate, message_crud
from app.database.crud.paper_crud import PaperUpdate, paper_crud
from app.database.crud.sanitization import sanitize_for_postgres
from app.repositories.upload_reservations import upload_reservation_repository
from app.database.crud.user_repository import user_repository
from app.database.crud.zotero_crud import zotero_crud
from app.database.crud.zotero_import_crud import zotero_import_crud
from app.database.database import engine, get_db
from app.database.models import (
    ConversationScopeType,
    Document,
    DocumentProcessingStatus,
    JobStatus,
    JobOperation,
    LibraryPaper,
    ProjectPaper,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
    ResearchItemKind,
    ResearchScopeType,
    ZoteroImportStatus,
)
from app.database.telemetry import track_event
from app.errors import AppError
from app.helpers.advisory_locks import AdvisoryLock, AdvisoryLockNamespace
from app.helpers.metadata_hydration import hydrate_paper_metadata
from app.helpers.jobs_webhooks import verify_jobs_webhook
from app.helpers.ai_limits import release_concurrency_by_id
from app.helpers.celery_config import get_webhook_base_url
from app.services.resource_quotas import can_user_auto_sync_zotero
from app.services.document_gc import collect_document_if_due
from app.llm.citation_handler import CitationHandler
from app.repositories.conversations import conversation_repository
from app.repositories.jobs import EnqueueJob, job_repository
from app.schemas.conversations import ConversationCreateRequest
from app.llm.token_credits import llm_usage_context, settle_token_usage
from app.schemas.jobs import (
    AudioOverviewTaskPayload,
    AudioOverviewWebhookData,
    DataTableTaskPayload,
    DataTableWebhookData,
    PdfParserUpgradeWebhookData,
    PDFProcessingResult,
    PdfProcessingWebhookData,
    TokenUsageEventPayload,
)
from app.schemas.user import CurrentUser
from app.services.zotero.service import (
    apply_zotero_annotations,
    auto_import_new_papers,
    sync_batch,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

webhook_router = APIRouter(dependencies=[Depends(verify_jobs_webhook)])


class JobClaimResponse(BaseModel):
    claimed: bool


class JobCallbackIdentity(BaseModel):
    task_id: uuid.UUID


class StorageDeleteCallback(JobCallbackIdentity):
    deleted_count: int


@webhook_router.post("/jobs/{job_id}/claim", response_model=JobClaimResponse)
def claim_durable_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    return JobClaimResponse(claimed=job_repository.claim(db, job_id=job_id) is not None)


@webhook_router.post("/jobs/{job_id}/heartbeat", response_model=JobClaimResponse)
def heartbeat_durable_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    updated = job_repository.heartbeat(db, job_id=job_id)
    db.commit()
    return JobClaimResponse(claimed=updated)


@webhook_router.post("/jobs/{job_id}/audio", response_model=JobClaimResponse)
async def complete_audio_job(
    job_id: uuid.UUID,
    webhook: AudioOverviewWebhookData,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    if job.operation != JobOperation.AUDIO_GENERATE.value:
        raise AppError(
            code="job_operation_mismatch",
            message="Job operation does not match callback",
            status_code=409,
        )
    if webhook.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback ID does not match",
            status_code=409,
        )

    if webhook.status == "failed":
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=webhook.error or "audio_generation_failed",
        )
        db.commit()
    else:
        task_payload = AudioOverviewTaskPayload.model_validate(job.payload)
        result = webhook.result
        if result is None:
            raise RuntimeError("validated_audio_callback_without_result")
        if result.research_item_id != task_payload.research_item_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Research output ID does not match",
                status_code=409,
            )
        _, changed = job_repository.complete(
            db,
            job_id=job_id,
            result=result.model_dump(mode="json"),
        )
        if changed:
            scope_type = ResearchScopeType(task_payload.scope_type)
            item = ResearchItem(
                id=result.research_item_id,
                kind=ResearchItemKind.AUDIO_OVERVIEW.value,
                created_by_id=job.requested_by_id,
                scope_type=scope_type.value,
                document_id=(
                    task_payload.scope_id
                    if scope_type == ResearchScopeType.DOCUMENT
                    else None
                ),
                project_id=(
                    task_payload.scope_id
                    if scope_type == ResearchScopeType.PROJECT
                    else None
                ),
                is_shared=True,
                source_job_id=job_id,
            )
            item.audio_overview = ResearchAudioOverview(
                title=result.title,
                transcript=result.transcript,
                citations=result.citations,
                s3_object_key=result.s3_object_key,
                voice_id=result.voice_id,
                model_version=result.model_version,
            )
            db.add(item)
        db.commit()

    if job.requested_by_id is not None:
        _settle_jobs_usage(job.requested_by_id, webhook.usage_events)
        await release_concurrency_by_id(
            user_id=job.requested_by_id,
            category="audio",
            operation_id=str(job_id),
        )
        await release_concurrency_by_id(
            user_id=job.requested_by_id,
            category="background",
            operation_id=str(job_id),
        )
    return JobClaimResponse(claimed=changed)


@webhook_router.post("/jobs/{job_id}/data-table", response_model=JobClaimResponse)
async def complete_data_table_job(
    job_id: uuid.UUID,
    webhook: DataTableWebhookData,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    if job.operation != JobOperation.DATA_TABLE_GENERATE.value:
        raise AppError(
            code="job_operation_mismatch",
            message="Job operation does not match callback",
            status_code=409,
        )
    if webhook.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback ID does not match",
            status_code=409,
        )
    if webhook.status == "failed":
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=webhook.error or "data_table_processing_failed",
        )
        db.commit()
    else:
        task_payload = DataTableTaskPayload.model_validate(job.payload)
        result = webhook.result
        if result is None:
            raise RuntimeError("validated_data_table_callback_without_result")
        if result.research_item_id != task_payload.research_item_id:
            raise AppError(
                code="job_callback_mismatch",
                message="Research output ID does not match",
                status_code=409,
            )
        _, changed = job_repository.complete(
            db,
            job_id=job_id,
            result=result.model_dump(mode="json"),
        )
        if changed:
            item = ResearchItem(
                id=result.research_item_id,
                kind=ResearchItemKind.DATA_TABLE.value,
                created_by_id=job.requested_by_id,
                scope_type=ResearchScopeType.PROJECT.value,
                project_id=job.project_id,
                is_shared=True,
                source_job_id=job_id,
            )
            item.data_table = ResearchDataTable(
                title=result.title,
                columns=result.columns,
                rows=[row.model_dump(mode="json") for row in result.rows],
                citations=[
                    citation.model_dump(mode="json")
                    for row in result.rows
                    for cell in row.values.values()
                    for citation in cell.citations
                ],
                row_failures=[str(paper_id) for paper_id in result.row_failures],
            )
            db.add(item)
        db.commit()

    if job.requested_by_id is not None:
        _settle_jobs_usage(job.requested_by_id, webhook.usage_events)
        await release_concurrency_by_id(
            user_id=job.requested_by_id,
            category="background",
            operation_id=str(job_id),
        )
    return JobClaimResponse(claimed=changed)


def _settle_jobs_usage(user_id: int, events: list[TokenUsageEventPayload]) -> None:
    for event in events:
        with llm_usage_context(
            user_id=user_id,
            feature=event.feature,
            operation_id=event.operation_id,
        ):
            settle_token_usage(
                model=event.model,
                reasoning_level=event.reasoning_level,
                provider_request_id=event.provider_request_id,
                prompt_tokens=event.prompt_tokens,
                completion_tokens=event.completion_tokens,
                reasoning_tokens=event.reasoning_tokens,
                cache_hit_tokens=event.cache_hit_tokens,
                cache_miss_tokens=event.cache_miss_tokens,
                total_tokens=event.total_tokens,
                idempotency_key=event.idempotency_key,
                status=event.status,
            )


def _complete_pdf_job(
    db: Session,
    *,
    job_id: uuid.UUID,
    result: PDFProcessingResult,
) -> bool:
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result=result.model_dump(mode="json"),
    )
    return changed


def _enqueue_parser_upgrade(
    db: Session,
    *,
    ingestion_job_id: uuid.UUID,
    document_id: uuid.UUID,
) -> uuid.UUID:
    """Persist MinerU continuation before publishing it to the worker."""
    upgrade_job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.PDF_PARSER_UPGRADE,
            requested_by_id=None,
            document_id=document_id,
            idempotency_key=f"pdf-parser-upgrade:{ingestion_job_id}",
            payload={
                "checkpoint_job_id": str(ingestion_job_id),
                "document_id": str(document_id),
            },
            task_name="upgrade_pdf_parser",
            queue="pdf_processing",
            task_kwargs={
                "job_id": str(ingestion_job_id),
                "webhook_url": (
                    f"{base_url}/api/webhooks/jobs/{upgrade_job_id}/pdf-upgrade"
                ),
                "claim_url": (f"{base_url}/api/webhooks/jobs/{upgrade_job_id}/claim"),
            },
            job_id=upgrade_job_id,
        ),
    )
    return upgrade_job_id


def _enqueue_pdf_postprocess(
    db: Session,
    *,
    ingestion_job_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: int,
) -> uuid.UUID:
    postprocess_job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.PDF_POSTPROCESS,
            requested_by_id=user_id,
            document_id=document_id,
            idempotency_key=f"pdf-postprocess:{ingestion_job_id}",
            payload={"ingestion_job_id": str(ingestion_job_id)},
            task_name="postprocess_pdf",
            queue="pdf_processing",
            task_kwargs={
                "callback_url": (
                    f"{base_url}/api/webhooks/jobs/{postprocess_job_id}/pdf-postprocess"
                ),
                "claim_url": (
                    f"{base_url}/api/webhooks/jobs/{postprocess_job_id}/claim"
                ),
            },
            job_id=postprocess_job_id,
        ),
    )
    return postprocess_job_id


def _finalize_zotero_import(
    db: Session,
    job_id: str,
    job_user: CurrentUser,
    result: "PDFProcessingResult",
    error_message: str | None = None,
) -> str | None:
    """
    Finalize a Zotero-imported paper from a jobs-worker result.

    The Zotero import path submits the PDF to the worker with LLM metadata
    extraction skipped, and applies Zotero's authoritative metadata
    (title/authors/abstract/DOI/publish_date) up front via
    _apply_metadata_from_zotero. So here we only fill in the deterministic worker
    outputs (preview, PDF text, page offsets, file size) and apply the Zotero
    annotations — we never require or overwrite the Zotero metadata.

    Used on the normal completion path (error_message=None) and as a best-effort
    salvage when the worker reports failure (error_message set) but still produced
    partial deterministic outputs (e.g. preview/text). Returns the paper id, or
    None when there is no Zotero metadata to keep (cannot finalize).
    """
    existing_paper = paper_crud.get_by_upload_job_id(
        db=db, upload_job_id=job_id, user=job_user
    )
    if not existing_paper or not getattr(existing_paper, "title", None):
        # No Zotero metadata was applied; cannot finalize.
        return None

    paper = paper_crud.update(
        db=db,
        obj_in=PaperUpdate(
            preview_s3_key=result.preview_s3_key,
            raw_content=result.raw_content,
            parser_markdown_s3_key=result.parser_markdown_s3_key,
            parser_archive_s3_key=result.parser_archive_s3_key,
            parser_backend=result.parser_backend,
            parser_quality=result.parser_quality,
            parser_version=result.parser_version,
            parser_warning_code=result.parser_warning_code,
            page_offset_map=result.page_offset_map,
            processing_status=DocumentProcessingStatus.COMPLETED.value,
        ),
        db_obj=existing_paper,
        user=job_user,
    )

    upload_reservation_repository.mark_as_completed(db=db, job_id=job_id, user=job_user)

    if not paper:
        return None

    # When salvaging a partial result, record the worker error on the import row.
    # apply_zotero_annotations (below) flips the row to COMPLETED but preserves
    # this note (it only sets error_message when given one).
    if error_message:
        zotero_import = zotero_import_crud.get_by_upload_job_id(
            db, upload_job_id=uuid.UUID(job_id)
        )
        if zotero_import:
            zotero_import_crud.update_status(
                db,
                item=zotero_import,
                status=ZoteroImportStatus.PROCESSING,
                error_message=f"Imported without full processing: {error_message}",
                paper_id=uuid.UUID(str(paper.id)),
            )

    try:
        apply_zotero_annotations(
            db=db,
            upload_job_id=job_id,
            paper_id=str(paper.id),
            user=job_user,
        )
    except Exception as e:
        logger.error(
            f"Error applying Zotero annotations for job {job_id}: {e}",
            exc_info=True,
        )

    logger.info(
        f"Finalized Zotero import for job {job_id} with paper {paper.id}"
        + (f" (worker error: {error_message})" if error_message else "")
    )
    return str(paper.id)


def handle_failed_upload(
    db: Session, job_id: str, job_user: CurrentUser, reason: str = "Unknown error"
) -> None:
    """
    Handle cleanup for a failed paper upload job.

    Removes the paper record and any associated ProjectPaper relationships
    that were created during the upload process.

    Args:
        db: Database session
        job_id: The upload job ID
        job_user: The user who owns the job
        reason: Description of why the upload failed
    """
    # Refuse to tear down a job that already succeeded. A redelivered Celery
    # task (acks_late) can post a late "failed" webhook after another delivery
    # already built and committed the paper; deleting it here is what caused
    # the highlights_paper_id_fkey violations (highlight inserts racing a paper
    # delete). A completed job means the paper is good — leave it alone.
    job = upload_reservation_repository.get(db=db, id=job_id, user=job_user)
    if job and job.job.status == JobStatus.COMPLETED:
        logger.warning(
            f"Ignoring failed-upload cleanup for already-completed job {job_id} "
            f"(reason: {reason}); refusing to delete a populated paper"
        )
        return

    logger.error(f"PDF processing failed for job {job_id}: {reason}")

    if job and job.job.document_id is not None:
        durable_job = job.job
        document_id = durable_job.document_id
        assert document_id is not None
        document = db.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if document is not None and document.processing_job_id == job.id:
            document.processing_status = DocumentProcessingStatus.FAILED.value
            document.parser_warning_code = "processing_failed"
        if job.reference_created:
            if durable_job.project_id is None:
                db.execute(
                    delete(LibraryPaper).where(
                        LibraryPaper.user_id == durable_job.requested_by_id,
                        LibraryPaper.document_id == document_id,
                    )
                )
            else:
                db.execute(
                    delete(ProjectPaper).where(
                        ProjectPaper.project_id == durable_job.project_id,
                        ProjectPaper.document_id == document_id,
                    )
                )
            db.flush()
            from app.services.document_gc import schedule_document_gc

            schedule_document_gc(db, document_id=document_id)

    upload_reservation_repository.mark_as_failed(db=db, job_id=job_id, user=job_user)
    try:
        job_repository.fail(
            db,
            job_id=uuid.UUID(job_id),
            error_code="pdf_processing_failed",
        )
        db.commit()
    except AppError as exc:
        if exc.code != "job_not_found":
            raise

    zotero_import = zotero_import_crud.get_by_upload_job_id(
        db, upload_job_id=uuid.UUID(job_id)
    )
    if zotero_import:
        zotero_import_crud.update_status(
            db,
            item=zotero_import,
            status=ZoteroImportStatus.FAILED,
            error_message=reason,
            paper_id=None,
        )


def post_process_paper(
    *,
    db: Session,
    paper: Document,
    job_user: CurrentUser,
) -> None:
    """Build search passages and hydrate metadata under a durable job lease."""
    if not paper.raw_content:
        raise RuntimeError("pdf_postprocess_content_missing")
    paper.attempted_metadata_at = datetime.now(timezone.utc)
    paper_crud.index_paper_passages(
        db,
        paper_id=paper.id,
        raw_content=paper.raw_content,
    )
    hydrated = hydrate_paper_metadata(
        db=db,
        paper=paper,
        user=job_user,
        force=True,
        agentic=True,
    )
    track_event(
        "doi_resolved",
        properties={"has_doi": bool(hydrated.doi)},
        user_id=str(job_user.id),
        db=db,
    )


@webhook_router.post(
    "/jobs/{job_id}/pdf-postprocess",
    response_model=JobClaimResponse,
)
def complete_pdf_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    if (
        job.operation != JobOperation.PDF_POSTPROCESS.value
        or callback.task_id != job_id
    ):
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback does not match",
            status_code=409,
        )
    if job.status == JobStatus.COMPLETED.value:
        return JobClaimResponse(claimed=False)
    if job.document_id is None or job.requested_by_id is None:
        raise AppError(
            code="job_scope_missing",
            message="Job scope is incomplete",
            status_code=409,
        )
    paper = db.get(Document, job.document_id)
    user = user_repository.get(db, id=job.requested_by_id)
    if paper is None or user is None:
        raise AppError(
            code="job_scope_missing",
            message="Job scope is no longer available",
            status_code=409,
        )
    try:
        post_process_paper(
            db=db,
            paper=paper,
            job_user=CurrentUser.from_auth_user(user),
        )
        job_repository.complete(
            db,
            job_id=job_id,
            result={"document_id": str(paper.id)},
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "PDF post-processing failed",
            extra={"job_id": str(job_id), "document_id": str(paper.id)},
        )
        raise
    return JobClaimResponse(claimed=True)


@webhook_router.post(
    "/jobs/{job_id}/document-gc",
    response_model=JobClaimResponse,
)
def complete_document_gc_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    if job.operation != JobOperation.DOCUMENT_GC.value or callback.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback does not match",
            status_code=409,
        )
    if job.status == JobStatus.COMPLETED.value:
        return JobClaimResponse(claimed=False)
    if job.document_id is None:
        job_repository.complete(
            db,
            job_id=job_id,
            result={"deleted": True, "cancelled": False},
        )
        db.commit()
        return JobClaimResponse(claimed=True)

    result = collect_document_if_due(db, document_id=job.document_id)
    if result.retry_required:
        raise AppError(
            code="document_gc_retry_required",
            message="Document cleanup will be retried",
            status_code=503,
        )
    if not result.deleted and not result.cancelled:
        raise AppError(
            code="document_gc_not_due",
            message="Document cleanup is not due",
            status_code=503,
        )
    job_repository.complete(
        db,
        job_id=job_id,
        result={
            "deleted": result.deleted,
            "cancelled": result.cancelled,
        },
    )
    db.commit()
    return JobClaimResponse(claimed=True)


@webhook_router.post(
    "/jobs/{job_id}/storage-delete",
    response_model=JobClaimResponse,
)
def complete_storage_delete_job(
    job_id: uuid.UUID,
    callback: StorageDeleteCallback,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    if job.operation != JobOperation.STORAGE_DELETE.value or callback.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback does not match",
            status_code=409,
        )
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result={"deleted_count": callback.deleted_count},
    )
    db.commit()
    return JobClaimResponse(claimed=changed)


@webhook_router.post("/paper-processing/{job_id}")
async def handle_paper_processing_webhook(
    job_id: str,
    webhook_data: PdfProcessingWebhookData,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Handle webhook from paper processing jobs service."""

    # Get the job from your database (without user filtering since this is a webhook)
    job = upload_reservation_repository.get_by(
        db=db, task_id=webhook_data.task_id, id=job_id
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_id = str(job.id)
    durable_job = job_repository.require(db, job_id=job.id)
    if durable_job.operation != JobOperation.PDF_PROCESS.value:
        raise AppError(
            code="job_operation_mismatch",
            message="Job operation does not match callback",
            status_code=409,
        )

    if durable_job.status == JobStatus.COMPLETED:
        logger.warning(f"Received webhook for already completed job {job_id}, ignoring")
        return {"status": "webhook ignored - job already completed"}

    # Get the user object from the relationship
    user = durable_job.requested_by
    if not user:
        logger.error(f"No user found for job {job_id}")
        raise HTTPException(status_code=500, detail="User not found for job")

    job_user: CurrentUser = CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=user.status,
        email_verified=user.email_verified_at is not None,
        locale=user.profile.locale if user.profile else None,
        is_admin=bool(user.profile and user.profile.is_admin),
        is_blocked=bool(user.profile and user.profile.is_blocked),
        is_active=user.status == "active",
    )
    _settle_jobs_usage(int(user.id), webhook_data.usage_events)
    if durable_job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
        logger.warning(
            "Ignoring late webhook for terminal job %s with status %s",
            job_id,
            durable_job.status,
        )
        await release_concurrency_by_id(
            user_id=int(user.id),
            category="background",
            operation_id=job_id,
        )
        return {"status": "webhook ignored - job is terminal"}

    # Serialize concurrent/duplicate deliveries for the same job. Celery retries
    # with acks_late, so a redelivered task can fire a second webhook while the
    # first is still processing. Without this, the two handlers race and one can
    # delete the paper out from under the other (FK violations on highlight
    # insert). Non-blocking: a loser bails immediately. The lock rides its own
    # connection so it survives this handler's many intermediate commits.
    job_lock = AdvisoryLock(
        engine, namespace=AdvisoryLockNamespace.PAPER_PROCESSING_WEBHOOK, key=job_id
    )
    if not job_lock.acquire():
        logger.warning(
            f"Webhook for job {job_id} is already being processed by another "
            f"delivery, ignoring duplicate"
        )
        return {"status": "webhook ignored - already being processed"}

    status = webhook_data.status
    result = webhook_data.result

    zotero_import = zotero_import_crud.get_by_upload_job_id(
        db, upload_job_id=uuid.UUID(job_id)
    )

    try:
        # Re-check completion under the lock: another delivery may have finished
        # between our initial read and acquiring the lock.
        db.refresh(durable_job)
        if durable_job.status == JobStatus.COMPLETED:
            logger.warning(
                f"Job {job_id} completed by a concurrent delivery, ignoring "
                f"duplicate webhook"
            )
            return {"status": "webhook ignored - job already completed"}
        if durable_job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
            logger.warning(
                "Job %s became terminal before webhook processing; ignoring",
                job_id,
            )
            return {"status": "webhook ignored - job is terminal"}

        if status == "completed" and result.success:
            # Zotero imports run the worker with LLM metadata extraction skipped,
            # so they have no `metadata` to apply. Zotero's authoritative metadata
            # was already set at submit time; here we only fill the deterministic
            # worker outputs and apply Zotero annotations.
            if zotero_import:
                finalized = _finalize_zotero_import(
                    db=db, job_id=job_id, job_user=job_user, result=result
                )
                if finalized:
                    _complete_pdf_job(db, job_id=job.id, result=result)
                    if (
                        result.parser_upgrade_pending
                        and durable_job.document_id is not None
                    ):
                        _enqueue_parser_upgrade(
                            db,
                            ingestion_job_id=job.id,
                            document_id=durable_job.document_id,
                        )
                    db.commit()
                    track_event(
                        "zotero_paper_processed",
                        properties={"worker_duration": result.duration},
                        user_id=str(user.id),
                        db=db,
                    )
                    return {
                        "status": "webhook processed - zotero import",
                        "paper_id": finalized,
                    }
                handle_failed_upload(
                    db=db,
                    job_id=job_id,
                    job_user=job_user,
                    reason="Zotero import missing metadata",
                )
                return {"status": "webhook processed - zotero import failed"}

            # Processing was successful
            metadata = result.metadata

            if not metadata or not metadata.title:
                logger.error(f"No metadata in webhook result for job {job_id}")
                handle_failed_upload(
                    db=db, job_id=job_id, job_user=job_user, reason="Missing metadata"
                )
                return {"status": "webhook processed - failed due to missing metadata"}

            if not result.raw_content:
                logger.error(f"No raw_content in webhook result for job {job_id}")
                handle_failed_upload(
                    db=db,
                    job_id=job_id,
                    job_user=job_user,
                    reason="Missing raw_content",
                )
                return {
                    "status": "webhook processed - failed due to missing raw_content"
                }

            publish_date = metadata.publish_date if metadata.publish_date else None

            existing_paper = paper_crud.get_by_upload_job_id(
                db=db, upload_job_id=job_id, user=job_user
            )

            # Create paper record
            if existing_paper is None:
                raise HTTPException(status_code=404, detail="paper_not_found")
            paper = paper_crud.update(
                db=db,
                obj_in=PaperUpdate(
                    preview_s3_key=result.preview_s3_key,
                    title=metadata.title,
                    authors=metadata.authors,
                    abstract=metadata.abstract,
                    summary="",
                    summary_citations=[],
                    institutions=metadata.institutions,
                    keywords=metadata.keywords,
                    publish_date=publish_date,
                    raw_content=result.raw_content,
                    parser_markdown_s3_key=result.parser_markdown_s3_key,
                    parser_archive_s3_key=result.parser_archive_s3_key,
                    parser_backend=result.parser_backend,
                    parser_quality=result.parser_quality,
                    parser_version=result.parser_version,
                    parser_warning_code=result.parser_warning_code,
                    page_offset_map=result.page_offset_map,
                    processing_status=DocumentProcessingStatus.COMPLETED.value,
                ),
                db_obj=existing_paper,
                user=job_user,
            )

            # Create highlights/annotations if any
            if metadata.highlights and paper:
                try:
                    paper_crud.create_ai_annotations(
                        db=db,
                        paper_id=str(paper.id),
                        extract_metadata=metadata,
                        current_user=job_user,
                    )
                except Exception:
                    logger.exception("Error creating annotations for job %s", job_id)
                    # Don't fail the whole process for annotation errors

            if metadata.summary and paper:
                try:
                    conversation_data = ConversationCreateRequest(
                        scope_type=ConversationScopeType.PAPER,
                        scope_id=uuid.UUID(str(paper.id)),
                    )

                    conversation = conversation_repository.create(
                        db,
                        request=conversation_data,
                        user_id=job_user.id,
                    )

                    if conversation:
                        # Add the summary as the first message in the conversation, from the AI

                        citations_dict = (
                            CitationHandler.convert_response_citation_to_paper_citation(
                                metadata.summary_citations
                            )
                        )

                        message_crud.create(
                            db,
                            obj_in=MessageCreate(
                                conversation_id=uuid.UUID(str(conversation.id)),
                                role="assistant",
                                content=metadata.summary,
                                references=dict(citations_dict),
                            ),
                            user=job_user,
                        )
                except Exception:
                    logger.exception(
                        "Error creating conversation/message for job %s", job_id
                    )
                    # Don't fail the whole process for conversation/message errors

            # Track metadata extraction event
            track_event(
                "extracted_metadata",
                properties={
                    "has_title": bool(metadata.title),
                    "has_authors": bool(metadata.authors),
                    "has_abstract": bool(metadata.abstract),
                    "has_summary": bool(metadata.summary),
                    "has_ai_highlights": bool(metadata.highlights),
                },
                user_id=str(user.id),
                db=db,
            )

            start_time = job.created_at
            end_time = datetime.now(timezone.utc)

            track_event(
                "paper_upload",
                properties={
                    "has_metadata": bool(metadata),
                    "duration": (end_time - start_time).total_seconds(),
                    "worker_duration": result.duration,
                },
                user_id=str(user.id),
                db=db,
            )

            # Mark job as completed
            upload_reservation_repository.mark_as_completed(
                db=db, job_id=job_id, user=job_user
            )
            _complete_pdf_job(
                db,
                job_id=uuid.UUID(job_id),
                result=result,
            )
            if paper is not None:
                db.commit()
                if result.parser_upgrade_pending:
                    _enqueue_parser_upgrade(
                        db,
                        ingestion_job_id=uuid.UUID(job_id),
                        document_id=uuid.UUID(str(paper.id)),
                    )
                    db.commit()

            if paper:
                _enqueue_pdf_postprocess(
                    db,
                    ingestion_job_id=uuid.UUID(job_id),
                    document_id=uuid.UUID(str(paper.id)),
                    user_id=job_user.id,
                )
                db.commit()

        else:
            # Processing failed.
            error_message = result.error if result.error else "Unknown error"

            # Best-effort salvage for Zotero imports: Zotero already supplied the
            # metadata, so keep the paper with whatever deterministic outputs the
            # worker did produce instead of discarding it.
            if zotero_import:
                salvaged = _finalize_zotero_import(
                    db=db,
                    job_id=job_id,
                    job_user=job_user,
                    result=result,
                    error_message=error_message,
                )
                if salvaged:
                    _complete_pdf_job(db, job_id=job.id, result=result)
                    if (
                        result.parser_upgrade_pending
                        and durable_job.document_id is not None
                    ):
                        _enqueue_parser_upgrade(
                            db,
                            ingestion_job_id=job.id,
                            document_id=durable_job.document_id,
                        )
                    db.commit()
                    return {
                        "status": "webhook processed - zotero salvage",
                        "paper_id": salvaged,
                    }

            handle_failed_upload(
                db=db, job_id=job_id, job_user=job_user, reason=error_message
            )

    except Exception as e:
        logger.exception("Error processing webhook for job %s", job_id)

        # Roll back before cleanup: the failure above may have left the session
        # in a PendingRollbackError state, which would otherwise make every
        # cleanup query (and mark_as_failed) fail too.
        db.rollback()

        # Clean up the paper record on exception as well
        try:
            handle_failed_upload(db=db, job_id=job_id, job_user=job_user, reason=str(e))
        except Exception as cleanup_error:
            logger.error(
                f"Failed to cleanup paper for job {job_id}: {str(cleanup_error)}"
            )
            # Still mark job as failed even if cleanup fails
            upload_reservation_repository.mark_as_failed(
                db=db, job_id=job_id, user=job_user
            )

        raise HTTPException(status_code=500, detail="Error processing webhook")
    finally:
        # Always release the advisory lock (and return its connection to the pool).
        job_lock.release()
        await release_concurrency_by_id(
            user_id=int(user.id),
            category="background",
            operation_id=job_id,
        )

    return {"status": "webhook processed"}


@webhook_router.post("/jobs/{job_id}/pdf-upgrade")
def handle_paper_parser_upgrade_webhook(
    job_id: uuid.UUID,
    webhook_data: PdfParserUpgradeWebhookData,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Atomically replace a completed text-only parse with MinerU output."""
    job = job_repository.require(db, job_id=job_id)
    if job.operation != JobOperation.PDF_PARSER_UPGRADE.value:
        raise AppError(
            code="job_operation_mismatch",
            message="Job operation does not match callback",
            status_code=409,
        )
    checkpoint_job_id = str(job.payload.get("checkpoint_job_id", ""))
    if webhook_data.result.job_id != checkpoint_job_id:
        raise HTTPException(status_code=422, detail="parser_upgrade_job_mismatch")
    if webhook_data.task_id != str(job_id):
        raise HTTPException(status_code=422, detail="parser_upgrade_task_mismatch")
    document_id = job.document_id
    if document_id is None:
        raise HTTPException(status_code=409, detail="parser_upgrade_document_missing")

    upgrade_lock = AdvisoryLock(
        engine,
        namespace=AdvisoryLockNamespace.PAPER_PROCESSING_WEBHOOK,
        key=str(document_id),
    )
    if not upgrade_lock.acquire():
        raise HTTPException(status_code=409, detail="paper_update_in_progress")

    try:
        paper = db.get(Document, document_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="paper_not_found")
        if paper.parser_quality == "full":
            job_repository.complete(
                db,
                job_id=job_id,
                result=webhook_data.result.model_dump(mode="json"),
            )
            db.commit()
            return {
                "status": "parser upgrade already applied",
                "paper_id": str(paper.id),
            }
        if paper.parser_quality != "text_only":
            raise HTTPException(status_code=409, detail="paper_not_text_only")

        result = webhook_data.result
        paper.raw_content = str(sanitize_for_postgres(result.raw_content))
        paper.page_offset_map = result.page_offset_map
        paper.parser_markdown_s3_key = result.parser_markdown_s3_key
        paper.parser_archive_s3_key = result.parser_archive_s3_key
        paper.parser_backend = result.parser_backend
        paper.parser_quality = result.parser_quality
        paper.parser_version = result.parser_version
        paper.parser_warning_code = None

        paper_crud.index_paper_passages(
            db,
            paper_id=uuid.UUID(str(paper.id)),
            raw_content=paper.raw_content,
        )
        job_repository.complete(
            db,
            job_id=job_id,
            result=result.model_dump(mode="json"),
        )
        db.commit()
        logger.info(
            "Applied MinerU parser upgrade",
            extra={
                "job_id": str(job_id),
                "paper_id": str(paper.id),
                "task_id": webhook_data.task_id,
                "phase": "parser_upgrade",
            },
        )
        return {
            "status": "parser upgrade applied",
            "paper_id": str(paper.id),
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Failed to apply MinerU parser upgrade",
            extra={"job_id": str(job_id), "phase": "parser_upgrade"},
        )
        raise HTTPException(
            status_code=500,
            detail="parser_upgrade_failed",
        ) from exc
    finally:
        upgrade_lock.release()


@webhook_router.post("/internal/zotero-schedule")
def schedule_zotero_jobs(
    request: Request, db: Session = Depends(get_db)
) -> dict[str, object]:
    """Persist one idempotent job per due and eligible Zotero user."""
    threshold_seconds = int(
        request.query_params.get("threshold_seconds", str(24 * 3600))
    )
    if threshold_seconds < 60:
        raise AppError(
            code="zotero_sync_interval_invalid",
            message="Zotero sync interval is invalid",
            status_code=422,
        )
    threshold_hours = threshold_seconds / 3600
    user_ids = zotero_import_crud.list_user_ids_due_for_sync(
        db, threshold_hours=threshold_hours
    )
    scheduled = 0
    skipped = 0
    window = int(datetime.now(timezone.utc).timestamp()) // threshold_seconds
    base_url = get_webhook_base_url().rstrip("/")
    for user_id in user_ids:
        user = user_repository.get(db, id=user_id)
        if not user:
            skipped += 1
            continue

        current_user = CurrentUser.from_auth_user(user)
        if not can_user_auto_sync_zotero(db, current_user):
            skipped += 1
            continue

        if not zotero_crud.get_by_user_id(db, user_id=user.id):
            skipped += 1
            continue
        job_id = uuid.uuid4()
        job = job_repository.enqueue(
            db,
            request=EnqueueJob(
                operation=JobOperation.ZOTERO_POSTPROCESS,
                requested_by_id=user.id,
                idempotency_key=f"zotero-postprocess:{user.id}:{window}",
                payload={"threshold_seconds": threshold_seconds},
                task_name="postprocess_zotero",
                queue="zotero_sync",
                task_kwargs={
                    "callback_url": (
                        f"{base_url}/api/webhooks/jobs/{job_id}/zotero-postprocess"
                    ),
                    "claim_url": f"{base_url}/api/webhooks/jobs/{job_id}/claim",
                },
                job_id=job_id,
            ),
        )
        if job.id == job_id:
            scheduled += 1
    db.commit()
    return {
        "total_users": len(user_ids),
        "scheduled_jobs": scheduled,
        "skipped_users": skipped,
    }


@webhook_router.post(
    "/jobs/{job_id}/zotero-postprocess",
    response_model=JobClaimResponse,
)
async def complete_zotero_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session = Depends(get_db),
) -> JobClaimResponse:
    job = job_repository.require(db, job_id=job_id)
    if (
        job.operation != JobOperation.ZOTERO_POSTPROCESS.value
        or callback.task_id != job_id
    ):
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback does not match",
            status_code=409,
        )
    if job.status == JobStatus.COMPLETED.value:
        return JobClaimResponse(claimed=False)
    if job.requested_by_id is None:
        raise AppError(
            code="job_scope_missing",
            message="Job scope is incomplete",
            status_code=409,
        )
    user = user_repository.get(db, id=job.requested_by_id)
    if user is None:
        job_repository.complete(
            db,
            job_id=job_id,
            result={"skipped": "user_not_found"},
        )
        db.commit()
        return JobClaimResponse(claimed=True)
    current_user = CurrentUser.from_auth_user(user)
    if (
        not can_user_auto_sync_zotero(db, current_user)
        or zotero_crud.get_by_user_id(db, user_id=user.id) is None
    ):
        job_repository.complete(
            db,
            job_id=job_id,
            result={"skipped": "not_eligible_or_disconnected"},
        )
        db.commit()
        return JobClaimResponse(claimed=True)

    try:
        sync_result = await sync_batch(db, user=current_user, limit=50)
        import_result = await auto_import_new_papers(db, user=current_user)
        synced_papers = int(sync_result.get("synced_papers_count", 0))
        annotation_count = int(sync_result.get("new_annotations_count", 0))
        imported_count = int(import_result.get("auto_imported_count", 0))
        job_repository.complete(
            db,
            job_id=job_id,
            result={
                "synced_papers_count": synced_papers,
                "new_annotations_count": annotation_count,
                "auto_imported_count": imported_count,
            },
        )
        db.commit()
        track_event(
            "zotero_auto_sync",
            user_id=str(user.id),
            properties={
                "papers": synced_papers,
                "annotations": annotation_count,
                "auto_imported": imported_count,
            },
            db=db,
        )
    except Exception:
        db.rollback()
        logger.exception(
            "Durable Zotero post-processing failed",
            extra={"job_id": str(job_id), "user_id": user.id},
        )
        raise
    return JobClaimResponse(claimed=True)
