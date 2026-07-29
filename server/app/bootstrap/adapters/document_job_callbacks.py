"""Cross-module PDF, storage, and Zotero callback adapter."""

import logging
import uuid
from datetime import datetime, timezone

from app.modules.conversations.infrastructure.message_repository import (
    MessageCreate,
    message_repository,
)
from app.bootstrap.adapters.upload_repository import (
    upload_reservation_repository,
)
from app.modules.identity.infrastructure.users import user_repository
from app.modules.integrations.zotero.infrastructure.connection_repository import (
    zotero_connection_repository,
)
from app.modules.integrations.zotero.infrastructure.import_repository import (
    zotero_import_repository,
)
from app.database.database import engine
from app.database.models import (
    ConversationScopeType,
    Document,
    DocumentProcessingStatus,
    JobStatus,
    JobOperation,
    LibraryPaper,
    ProjectPaper,
    ZoteroImportStatus,
)
from app.shared.domain import JsonValue
from app.database.telemetry import track_event
from app.shared.domain import AppError
from app.helpers.advisory_locks import AdvisoryLock, AdvisoryLockNamespace
from app.helpers.metadata_hydration import hydrate_paper_metadata
from app.helpers.ai_limits import release_concurrency_by_id
from app.helpers.celery_config import get_webhook_base_url
from app.modules.billing.infrastructure.quotas import can_user_auto_sync_zotero
from app.modules.papers.infrastructure.garbage_collection import collect_document_if_due
from app.llm.citation_handler import CitationHandler
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.modules.papers.infrastructure.search_repository import (
    document_search_repository,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
)
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.jobs.application.contracts import (
    JobCallbackIdentity,
    JobClaimResponse,
    PDFProcessingResult,
    PdfProcessingWebhookData,
    StorageDeleteCallback,
)
from app.shared.application import Actor
from app.modules.identity.infrastructure.users import actor_from_auth_user
from app.bootstrap.adapters.zotero_workflow import (
    apply_zotero_annotations,
    auto_import_new_papers,
    sync_batch,
)
from app.bootstrap.adapters.research_annotations import (
    create_ai_highlights,
)
from app.modules.jobs.infrastructure.callback_boundaries import (
    callback_transaction,
    optional_savepoint,
    pdf_ingestion_callback,
)
from pydantic import TypeAdapter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.jobs.infrastructure.research_callbacks import settle_jobs_usage

logger = logging.getLogger(__name__)

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


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
                    f"{base_url}/internal/v1/jobs/{postprocess_job_id}/complete"
                ),
                "claim_url": (
                    f"{base_url}/internal/v1/jobs/{postprocess_job_id}/claim"
                ),
            },
            job_id=postprocess_job_id,
        ),
    )
    return postprocess_job_id


def _finalize_zotero_import(
    db: Session,
    job_id: str,
    job_user: Actor,
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
    existing_paper = document_repository.find_by_upload_job(
        db=db, upload_job_id=job_id, user=job_user
    )
    if not existing_paper or not getattr(existing_paper, "title", None):
        # No Zotero metadata was applied; cannot finalize.
        return None

    paper = document_repository.update_canonical(
        db,
        update=DocumentUpdate(
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
        document=existing_paper,
        user=job_user,
        refresh_result=False,
    )

    upload_reservation_repository.mark_as_completed(db=db, job_id=job_id, user=job_user)

    if not paper:
        return None

    # When salvaging a partial result, record the worker error on the import row.
    # apply_zotero_annotations (below) flips the row to COMPLETED but preserves
    # this note (it only sets error_message when given one).
    if error_message:
        zotero_import = zotero_import_repository.get_by_upload_job_id(
            db, upload_job_id=uuid.UUID(job_id)
        )
        if zotero_import:
            zotero_import_repository.update_status(
                db,
                item=zotero_import,
                status=ZoteroImportStatus.PROCESSING,
                error_message=f"Imported without full processing: {error_message}",
                document_id=uuid.UUID(str(paper.id)),
            )

    apply_zotero_annotations(
        db=db,
        upload_job_id=job_id,
        document_id=str(paper.id),
        user=job_user,
    )

    logger.info(
        f"Finalized Zotero import for job {job_id} with paper {paper.id}"
        + (f" (worker error: {error_message})" if error_message else "")
    )
    return str(paper.id)


def handle_failed_upload(
    db: Session, job_id: str, job_user: Actor, reason: str = "Unknown error"
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
    # the highlights_document_id_fkey violations (highlight inserts racing a paper
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
            from app.modules.papers.infrastructure.garbage_collection import (
                schedule_document_gc,
            )

            schedule_document_gc(db, document_id=document_id)

    upload_reservation_repository.mark_as_failed(db=db, job_id=job_id, user=job_user)
    try:
        job_repository.fail(
            db,
            job_id=uuid.UUID(job_id),
            error_code="pdf_processing_failed",
        )
    except AppError as exc:
        if exc.code != "job_not_found":
            raise

    zotero_import = zotero_import_repository.get_by_upload_job_id(
        db, upload_job_id=uuid.UUID(job_id)
    )
    if zotero_import:
        zotero_import_repository.update_status(
            db,
            item=zotero_import,
            status=ZoteroImportStatus.FAILED,
            error_message=reason,
            document_id=None,
        )


def post_process_paper(
    *,
    db: Session,
    paper: Document,
    job_user: Actor,
) -> None:
    """Build search passages and hydrate metadata under a durable job lease."""
    if not paper.raw_content:
        raise RuntimeError("pdf_postprocess_content_missing")
    paper.attempted_metadata_at = datetime.now(timezone.utc)
    document_search_repository.replace_passage_index(
        db,
        document_id=paper.id,
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


def complete_pdf_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
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
    with callback_transaction(
        db,
        operation="pdf_postprocess",
        context={"job_id": str(job_id), "document_id": str(paper.id)},
    ):
        post_process_paper(
            db=db,
            paper=paper,
            job_user=actor_from_auth_user(user),
        )
        job_repository.complete(
            db,
            job_id=job_id,
            result={"document_id": str(paper.id)},
        )
    return JobClaimResponse(claimed=True)


def complete_document_gc_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
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
    return JobClaimResponse(claimed=True)


def complete_storage_delete_job(
    job_id: uuid.UUID,
    callback: StorageDeleteCallback,
    db: Session,
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
    return JobClaimResponse(claimed=changed)


async def handle_paper_processing_webhook(
    job_id: str,
    webhook_data: PdfProcessingWebhookData,
    db: Session,
) -> dict[str, object]:
    """Handle webhook from paper processing jobs service."""

    # Get the job from your database (without user filtering since this is a webhook)
    job = upload_reservation_repository.get_by(
        db=db, task_id=webhook_data.task_id, id=job_id
    )
    if not job:
        raise AppError(
            code="job_not_found",
            message="Job not found",
            status_code=404,
        )

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
        raise AppError(
            code="job_requester_missing",
            message="The job requester is unavailable",
            status_code=409,
        )

    job_user: Actor = Actor(
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
    settle_jobs_usage(int(user.id), webhook_data.usage_events)
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

    zotero_import = zotero_import_repository.get_by_upload_job_id(
        db, upload_job_id=uuid.UUID(job_id)
    )

    def mark_callback_failed() -> None:
        upload_reservation_repository.mark_as_failed(
            db=db,
            job_id=job_id,
            user=job_user,
            error_code="webhook_processing_failed",
        )

    async with pdf_ingestion_callback(
        db,
        lock=job_lock,
        user_id=int(user.id),
        operation_id=job_id,
        cleanup=lambda: handle_failed_upload(
            db=db,
            job_id=job_id,
            job_user=job_user,
            reason="webhook_processing_failed",
        ),
        fallback_mark_failed=mark_callback_failed,
    ):
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
                    track_event(
                        "zotero_paper_processed",
                        properties={"worker_duration": result.duration},
                        user_id=str(user.id),
                        db=db,
                    )
                    return {
                        "status": "webhook processed - zotero import",
                        "document_id": finalized,
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

            existing_paper = document_repository.find_by_upload_job(
                db=db, upload_job_id=job_id, user=job_user
            )

            # Create paper record
            if existing_paper is None:
                raise AppError(
                    code="paper_not_found",
                    message="Paper not found",
                    status_code=404,
                )
            paper = document_repository.update_canonical(
                db,
                update=DocumentUpdate(
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
                document=existing_paper,
                user=job_user,
                refresh_result=False,
            )

            # Create highlights/annotations if any
            if metadata.highlights and paper:
                with optional_savepoint(
                    db,
                    operation="create_ai_highlights",
                    context={"job_id": job_id, "document_id": str(paper.id)},
                ):
                    create_ai_highlights(
                        db,
                        document_id=paper.id,
                        metadata=metadata,
                        user=job_user,
                    )

            if metadata.summary and paper:
                with optional_savepoint(
                    db,
                    operation="create_summary_conversation",
                    context={"job_id": job_id, "document_id": str(paper.id)},
                ):
                    conversation_data = ConversationCreateRequest(
                        scope_type=ConversationScopeType.PAPER,
                        scope_id=uuid.UUID(str(paper.id)),
                    )

                    conversation = conversation_repository.create(
                        db,
                        request=conversation_data,
                        user_id=job_user.id,
                        refresh_result=False,
                    )

                    if conversation:
                        # Add the summary as the first message in the conversation, from the AI

                        citations_dict = (
                            CitationHandler.convert_response_citation_to_paper_citation(
                                metadata.summary_citations
                            )
                        )

                        message_repository.create(
                            db,
                            request=MessageCreate(
                                conversation_id=uuid.UUID(str(conversation.id)),
                                role="assistant",
                                content=metadata.summary,
                                references=_JSON_OBJECT.validate_python(citations_dict),
                            ),
                            user_id=job_user.id,
                            refresh_result=False,
                        )

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
            if paper:
                _enqueue_pdf_postprocess(
                    db,
                    ingestion_job_id=uuid.UUID(job_id),
                    document_id=uuid.UUID(str(paper.id)),
                    user_id=job_user.id,
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
                    _complete_pdf_job(db, job_id=job.id, result=result)
                    return {
                        "status": "webhook processed - zotero salvage",
                        "document_id": salvaged,
                    }

            handle_failed_upload(
                db=db, job_id=job_id, job_user=job_user, reason=error_message
            )

    return {"status": "webhook processed"}


def schedule_zotero_jobs(*, threshold_seconds: int, db: Session) -> dict[str, int]:
    """Persist one idempotent job per due and eligible Zotero user."""
    threshold_hours = threshold_seconds / 3600
    user_ids = zotero_import_repository.list_user_ids_due_for_sync(
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

        current_user = actor_from_auth_user(user)
        if not can_user_auto_sync_zotero(db, current_user):
            skipped += 1
            continue

        if not zotero_connection_repository.get_by_user_id(db, user_id=user.id):
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
                    "callback_url": (f"{base_url}/internal/v1/jobs/{job_id}/complete"),
                    "claim_url": f"{base_url}/internal/v1/jobs/{job_id}/claim",
                },
                job_id=job_id,
            ),
        )
        if job.id == job_id:
            scheduled += 1
    return {
        "total_users": len(user_ids),
        "scheduled_jobs": scheduled,
        "skipped_users": skipped,
    }


async def complete_zotero_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
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
        return JobClaimResponse(claimed=True)
    current_user = actor_from_auth_user(user)
    if (
        not can_user_auto_sync_zotero(db, current_user)
        or zotero_connection_repository.get_by_user_id(db, user_id=user.id) is None
    ):
        job_repository.complete(
            db,
            job_id=job_id,
            result={"skipped": "not_eligible_or_disconnected"},
        )
        return JobClaimResponse(claimed=True)

    with callback_transaction(
        db,
        operation="zotero_postprocess",
        context={"job_id": str(job_id), "user_id": user.id},
    ):
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
    return JobClaimResponse(claimed=True)
