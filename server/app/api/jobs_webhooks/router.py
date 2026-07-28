"""Signed webhook handlers for Scholens Jobs service integrations."""

import logging
import uuid
from datetime import datetime, timezone

from app.database.crud.message_crud import MessageCreate, message_crud
from app.database.crud.paper_crud import PaperUpdate, paper_crud
from app.database.crud.sanitization import sanitize_for_postgres
from app.database.crud.paper_upload_crud import paper_upload_job_crud
from app.database.crud.projects.project_data_table_crud import (
    DataTableResultCreate,
    DataTableRowCreate,
    data_table_job_crud,
    data_table_result_crud,
    data_table_row_crud,
)
from app.database.crud.user_repository import user_repository
from app.database.crud.zotero_crud import zotero_crud
from app.database.crud.zotero_import_crud import zotero_import_crud
from app.database.database import SessionLocal, engine, get_db
from app.database.models import (
    ConversationScopeType,
    Document,
    DocumentProcessingStatus,
    JobStatus,
    LibraryPaper,
    PaperUploadJob,
    ProjectPaper,
    ZoteroImportStatus,
)
from app.database.telemetry import track_event
from app.helpers.advisory_locks import AdvisoryLock, AdvisoryLockNamespace
from app.helpers.email import send_data_table_complete_email
from app.helpers.metadata_hydration import hydrate_paper_metadata
from app.helpers.jobs_webhooks import verify_jobs_webhook
from app.helpers.ai_limits import release_concurrency_by_id
from app.services.resource_quotas import can_user_auto_sync_zotero
from app.llm.citation_handler import CitationHandler
from app.repositories.conversations import conversation_repository
from app.schemas.conversations import ConversationCreateRequest
from app.llm.conversation_operations import data_table_operations
from app.llm.token_credits import llm_usage_context, settle_token_usage
from app.schemas.jobs import (
    PdfParserUpgradeWebhookData,
    PDFProcessingResult,
    PdfProcessingWebhookData,
    TokenUsageEventPayload,
)
from app.schemas.responses import DataTableResult
from app.schemas.user import CurrentUser
from app.services.zotero.service import (
    apply_zotero_annotations,
    auto_import_new_papers,
    sync_batch,
)
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

webhook_router = APIRouter(dependencies=[Depends(verify_jobs_webhook)])


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

    paper_upload_job_crud.mark_as_completed(db=db, job_id=job_id, user=job_user)

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
    job = paper_upload_job_crud.get(db=db, id=job_id, user=job_user)
    if job and job.status == JobStatus.COMPLETED:
        logger.warning(
            f"Ignoring failed-upload cleanup for already-completed job {job_id} "
            f"(reason: {reason}); refusing to delete a populated paper"
        )
        return

    logger.error(f"PDF processing failed for job {job_id}: {reason}")

    if job and job.document_id is not None:
        document = db.scalar(
            select(Document).where(Document.id == job.document_id).with_for_update()
        )
        if document is not None and document.processing_job_id == job.id:
            document.processing_status = DocumentProcessingStatus.FAILED.value
            document.parser_warning_code = "processing_failed"
        if job.reference_created:
            if job.project_id is None:
                db.execute(
                    delete(LibraryPaper).where(
                        LibraryPaper.user_id == job.user_id,
                        LibraryPaper.document_id == job.document_id,
                    )
                )
            else:
                db.execute(
                    delete(ProjectPaper).where(
                        ProjectPaper.project_id == job.project_id,
                        ProjectPaper.document_id == job.document_id,
                    )
                )
            db.flush()
            from app.services.document_gc import schedule_document_gc

            schedule_document_gc(db, document_id=job.document_id)

    paper_upload_job_crud.mark_as_failed(db=db, job_id=job_id, user=job_user)

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
    paper_id: uuid.UUID,
    raw_content: str,
    title: str,
    authors: list[str],
    job_user: CurrentUser,
) -> None:
    """Run paper post-processing (passage FTS indexing, DOI lookup) off the webhook hot path."""
    db = SessionLocal()
    try:
        # Stamp attempted_metadata_at up front so a concurrent GET /paper
        # short-circuits its own synchronous DOI lookup while we work.
        try:
            paper = paper_crud.get(db=db, id=paper_id, user=job_user)
            if paper:
                paper_crud.update(
                    db=db,
                    obj_in=PaperUpdate(
                        attempted_metadata_at=datetime.now(timezone.utc)
                    ),
                    db_obj=paper,
                    user=job_user,
                )
        except Exception:
            db.rollback()
            logger.exception(
                "Error stamping attempted_metadata_at for paper %s", paper_id
            )

        try:
            paper_crud.index_paper_passages(
                db,
                paper_id=paper_id,
                raw_content=raw_content,
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Error indexing passages for paper %s", paper_id)

        doi: str | None = None
        try:
            paper = paper_crud.get(db=db, id=paper_id, user=job_user)
            if paper:
                paper = hydrate_paper_metadata(
                    db=db, paper=paper, user=job_user, force=True, agentic=True
                )
                doi = str(paper.doi) if paper.doi else None
        except Exception:
            db.rollback()
            logger.exception("Error hydrating metadata for paper %s", paper_id)

        track_event(
            "doi_resolved",
            properties={"has_doi": bool(doi)},
            user_id=str(job_user.id),
            db=db,
        )
    finally:
        db.close()


@webhook_router.post("/paper-processing/{job_id}")
async def handle_paper_processing_webhook(
    job_id: str,
    webhook_data: PdfProcessingWebhookData,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Handle webhook from paper processing jobs service."""

    # Get the job from your database (without user filtering since this is a webhook)
    job = paper_upload_job_crud.get_by(db=db, task_id=webhook_data.task_id, id=job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_id = str(job.id)

    if job.status == JobStatus.COMPLETED:
        logger.warning(f"Received webhook for already completed job {job_id}, ignoring")
        return {"status": "webhook ignored - job already completed"}

    # Get the user object from the relationship
    user = job.user
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
    if job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
        logger.warning(
            "Ignoring late webhook for terminal job %s with status %s",
            job_id,
            job.status,
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
        db.refresh(job)
        if job.status == JobStatus.COMPLETED:
            logger.warning(
                f"Job {job_id} completed by a concurrent delivery, ignoring "
                f"duplicate webhook"
            )
            return {"status": "webhook ignored - job already completed"}
        if job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
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
            paper_upload_job_crud.mark_as_completed(db=db, job_id=job_id, user=job_user)
            if paper is not None:
                db.execute(
                    update(PaperUploadJob)
                    .where(
                        PaperUploadJob.document_id == paper.id,
                        PaperUploadJob.status.in_(
                            (JobStatus.PENDING.value, JobStatus.RUNNING.value)
                        ),
                    )
                    .values(
                        status=JobStatus.COMPLETED.value,
                        completed_at=datetime.now(timezone.utc),
                        error_code=None,
                    )
                )
                db.commit()

            if paper:
                background_tasks.add_task(
                    post_process_paper,
                    paper_id=uuid.UUID(str(paper.id)),
                    raw_content=result.raw_content,
                    title=metadata.title,
                    authors=metadata.authors,
                    job_user=job_user,
                )

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
            paper_upload_job_crud.mark_as_failed(db=db, job_id=job_id, user=job_user)

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


@webhook_router.post("/paper-parser-upgrade/{job_id}")
def handle_paper_parser_upgrade_webhook(
    job_id: str,
    webhook_data: PdfParserUpgradeWebhookData,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Atomically replace a completed text-only parse with MinerU output."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_job_id") from exc
    if webhook_data.result.job_id != job_id:
        raise HTTPException(status_code=422, detail="parser_upgrade_job_mismatch")

    job = paper_upload_job_crud.get_by(db=db, id=job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail="upload_job_not_found")
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="upload_job_not_completed")

    upgrade_lock = AdvisoryLock(
        engine,
        namespace=AdvisoryLockNamespace.PAPER_PROCESSING_WEBHOOK,
        key=job_id,
    )
    if not upgrade_lock.acquire():
        raise HTTPException(status_code=409, detail="paper_update_in_progress")

    try:
        paper = db.get(Document, job.document_id) if job.document_id else None
        if paper is None:
            raise HTTPException(status_code=404, detail="paper_not_found")
        if paper.parser_quality == "full":
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
        db.commit()
        logger.info(
            "Applied MinerU parser upgrade",
            extra={
                "job_id": job_id,
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
            extra={"job_id": job_id, "phase": "parser_upgrade"},
        )
        raise HTTPException(
            status_code=500,
            detail="parser_upgrade_failed",
        ) from exc
    finally:
        upgrade_lock.release()


class DataTableProcessingResultWebhookData(BaseModel):
    """Schema for webhook data from data table processing service."""

    task_id: str
    status: str
    result: DataTableResult | None = None
    error: str | None = None
    usage_events: list[TokenUsageEventPayload] = Field(default_factory=list)


@webhook_router.post("/data-table-processing/{job_id}")
async def handle_data_table_processing_webhook(
    job_id: str,
    webhook_data: DataTableProcessingResultWebhookData,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """Handle webhook from data table processing jobs service."""

    logger.info(
        f"Received data table processing webhook for job {job_id} with status {webhook_data.status}"
    )

    task_id = webhook_data.task_id
    status = webhook_data.status
    error = webhook_data.error
    job = data_table_job_crud.get_by_task_id(db=db, task_id=task_id)
    if not job or not job.user:
        raise HTTPException(status_code=404, detail="Data table job not found")
    _settle_jobs_usage(int(job.user.id), webhook_data.usage_events)

    result = webhook_data.result
    if result is None:
        data_table_job_crud.update_status(
            db=db,
            job_id=uuid.UUID(job_id),
            status=JobStatus.FAILED,
            error_message=error or "data_table_processing_failed",
        )
        await release_concurrency_by_id(
            user_id=int(job.user.id),
            category="background",
            operation_id=job_id,
        )
        return {
            "status": "data table webhook processed",
            "job_id": job_id,
            "task_id": task_id,
            "success": False,
            "rows_count": 0,
        }

    try:
        if status == "completed" and result.success:
            # Processing was successful
            logger.info(
                f"Data table processing completed for job {job_id}, "
                f"extracted {len(result.rows)} rows with columns: {result.columns}"
            )

            # Update job status to completed
            data_table_job_crud.update_status(
                db=db,
                job_id=uuid.UUID(job_id),
                status=JobStatus.COMPLETED,
            )

            # Post-Processing
            # Augment the DataCellValue citations with the paper_id
            # The job only returns citation info without paper_id, but we can fill it in here
            for col in result.columns:
                for row in result.rows:
                    cell_value = row.values.get(col)
                    if cell_value:
                        for citation in cell_value.citations:
                            citation.paper_id = row.paper_id

            paper_titles = []
            for row in result.rows:
                paper = paper_crud.get(db=db, id=uuid.UUID(row.paper_id))
                if paper and paper.title:
                    paper_titles.append(paper.title)
                else:
                    paper_titles.append("")

            with llm_usage_context(
                user_id=int(job.user.id),
                feature="data_table_naming",
                operation_id=f"{task_id}:name",
            ):
                title = (
                    data_table_operations.name_data_table(
                        paper_titles=paper_titles,
                        column_labels=result.columns,
                    )
                    or f"Data Table ({', '.join(result.columns)})"
                )

            # Create the data table result
            table_result = data_table_result_crud.create(
                db=db,
                obj_in=DataTableResultCreate(
                    job_id=uuid.UUID(job_id),
                    title=title,
                    success=result.success,
                    columns=result.columns,
                    row_failures=[uuid.UUID(pid) for pid in result.row_failures],
                ),
            )

            if table_result:
                # Create all rows using create_many
                # Convert DataTableCellValue objects to dicts for JSON serialization
                row_creates = [
                    DataTableRowCreate(
                        data_table_id=uuid.UUID(str(table_result.id)),
                        paper_id=uuid.UUID(row.paper_id),
                        values={
                            col: cell.model_dump() for col, cell in row.values.items()
                        },
                    )
                    for row in result.rows
                ]
                if row_creates:
                    data_table_row_crud.create_many(db=db, rows=row_creates)
                    logger.info(
                        f"Created {len(row_creates)} rows for data table result {table_result.id}"
                    )

                # Send email notification to user
                if job and job.user and job.project:
                    try:
                        send_data_table_complete_email(
                            to_email=job.user.email,
                            table_title=title,
                            columns=result.columns,
                            row_count=len(result.rows),
                            project_name=job.project.title or "Untitled project",
                            project_id=str(job.project.id),
                            result_id=str(table_result.id),
                        )
                    except Exception as email_error:
                        logger.error(
                            f"Failed to send data table complete email for job {job_id}: {email_error}",
                            exc_info=True,
                        )
            else:
                logger.error(f"Failed to create data table result for job {job_id}")

        else:
            # Processing failed
            error_message = error if error else "Unknown error"
            logger.error(
                f"Data table processing failed for job {job_id}: {error_message}"
            )

            # Update job status to failed
            data_table_job_crud.update_status(
                db=db,
                job_id=uuid.UUID(job_id),
                status=JobStatus.FAILED,
                error_message=error_message,
            )

    except Exception:
        logger.exception("Error processing data table webhook for job %s", job_id)
        raise HTTPException(status_code=500, detail="Error processing webhook")
    finally:
        await release_concurrency_by_id(
            user_id=int(job.user.id),
            category="background",
            operation_id=job_id,
        )

    return {
        "status": "data table webhook processed",
        "job_id": job_id,
        "task_id": task_id,
        "success": result.success,
        "rows_count": len(result.rows),
    }


@webhook_router.post("/internal/zotero-sync-all")
async def trigger_zotero_sync_all(
    request: Request, db: Session = Depends(get_db)
) -> dict[str, object]:
    """
    Internal endpoint called by the Celery Beat periodic task to sync new Zotero
    annotations for all users whose items haven't been synced in the past 24 hours.
    Authentication is enforced by the router's signed Jobs request dependency.
    """
    threshold_seconds = int(
        request.query_params.get("threshold_seconds", str(24 * 3600))
    )
    threshold_hours = threshold_seconds / 3600
    user_ids = zotero_import_crud.list_user_ids_due_for_sync(
        db, threshold_hours=threshold_hours
    )
    logger.info(
        f"Periodic Zotero sync: found {len(user_ids)} users due for sync (threshold={threshold_hours:.4f}h)"
    )

    results = []
    skipped = []
    for user_id in user_ids:
        user = user_repository.get(db, id=user_id)
        if not user:
            logger.info(f"Skipping Zotero auto-sync for {user_id}: user not found")
            skipped.append({"user_id": str(user_id), "reason": "user_not_found"})
            continue

        current_user = CurrentUser.from_auth_user(user)
        if not can_user_auto_sync_zotero(db, current_user):
            logger.info(
                f"Skipping Zotero auto-sync for {user_id}: not eligible for auto-sync (basic plan)"
            )
            skipped.append(
                {"user_id": str(user_id), "reason": "auto_sync_not_eligible"}
            )
            continue

        if not zotero_crud.get_by_user_id(db, user_id=user.id):
            # The user disconnected Zotero but kept their imported papers, so
            # their imported items still make them look "due for sync". This is
            # an expected, benign state — skip quietly rather than erroring.
            logger.info(
                f"Skipping Zotero auto-sync for {user_id}: Zotero account not connected"
            )
            skipped.append({"user_id": str(user_id), "reason": "not_connected"})
            continue

        try:
            result = await sync_batch(db, user=current_user, limit=50)
            results.append({"user_id": str(user_id), **result})
            if result.get("new_annotations_count", 0) > 0:
                track_event(
                    "zotero_auto_sync",
                    user_id=str(user_id),
                    properties={
                        "papers": result.get("synced_papers_count", 0),
                        "annotations": result.get("new_annotations_count", 0),
                    },
                    db=db,
                )

            # Auto-import is a best-effort secondary step. A failure here
            # shouldn't fail the user's sync (which already succeeded above), but
            # we still log it so the error is visible rather than swallowed.
            try:
                import_result = await auto_import_new_papers(db, user=current_user)
                if import_result.get("auto_imported_count", 0) > 0:
                    track_event(
                        "zotero_auto_import_new_papers",
                        user_id=str(user_id),
                        properties={"count": import_result["auto_imported_count"]},
                        db=db,
                    )
            except Exception as e:
                logger.error(
                    f"Auto-import of new papers failed for user {user_id}: {e}",
                    exc_info=True,
                )
        except Exception:
            logger.exception("Auto-sync failed for user %s", user_id)
            results.append({"user_id": str(user_id), "error": "zotero_sync_failed"})

    synced_users = len([r for r in results if "error" not in r])
    logger.info(
        f"Periodic Zotero sync complete: {synced_users}/{len(user_ids)} users synced "
        f"successfully, {len(skipped)} skipped"
    )
    return {
        "synced_users": synced_users,
        "total_users": len(user_ids),
        "skipped_users": len(skipped),
        "results": results,
        "skipped": skipped,
    }
