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
    RoleType,
    ZoteroImportStatus,
)
from app.shared.domain import JsonValue
from app.shared.domain import AppError, FailureKind
from app.helpers.advisory_locks import AdvisoryLock, AdvisoryLockNamespace
from app.helpers.celery_config import get_webhook_base_url
from app.modules.billing.infrastructure.quotas import can_user_auto_sync_zotero
from app.bootstrap.adapters.document_gc import collect_document_if_due
from app.modules.papers.application.citation_references import (
    materialize_summary_references,
)
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.modules.papers.infrastructure.search_repository import (
    document_search_repository,
)
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.domain import (
    can_complete_processing,
    can_fail_processing,
)
from app.modules.jobs.infrastructure.repository import (
    EnqueueJob,
    PersistedJob,
    job_repository,
)
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
    TokenUsageEventPayload,
)
from app.modules.jobs.application.callbacks import (
    JobHandlerResult,
    JobPostCommitAction,
    PdfPostprocessResolution,
    RecordJobTelemetry,
    ReleaseJobConcurrency,
    ScheduledZoteroJobs,
    SettleJobUsage,
)
from app.modules.jobs.application.actions import JOB_CREATED
from app.modules.papers.application.actions import (
    DOCUMENT_DELETED,
    DOCUMENT_METADATA_HYDRATED,
    DOCUMENT_PROCESSING_COMPLETED,
    DOCUMENT_PROCESSING_FAILED,
)
from app.modules.research.application.items import (
    RESEARCH_ANNOTATION_COMMENT_CREATED,
    RESEARCH_HIGHLIGHT_CREATED,
)
from app.modules.conversations.application.chat import (
    CONVERSATION_MESSAGE_CREATED,
)
from app.modules.conversations.application.conversations import (
    CONVERSATION_CREATED,
)
from app.modules.integrations.zotero.application.actions import (
    ZOTERO_IMPORT_COMPLETED,
)
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    ResourceRef,
)
from app.shared.application import Actor, OperationContext
from app.modules.papers.domain.citations import fields_from_paper
from app.bootstrap.workflows.pdf_postprocess import (
    PdfPostprocessReader,
    PdfPostprocessSnapshot,
)
from app.modules.identity.infrastructure.users import actor_from_auth_user
from app.bootstrap.adapters.zotero_annotations import (
    apply_persisted_zotero_annotations,
)
from app.bootstrap.adapters.research_annotations import (
    create_ai_highlights,
)
from app.modules.jobs.infrastructure.callback_boundaries import optional_savepoint
from pydantic import TypeAdapter
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

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
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> PersistedJob:
    postprocess_job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    return job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.PDF_POSTPROCESS,
            requested_by_id=user_id,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
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

    if not paper:
        return None

    # When salvaging a partial result, record the worker error on the import row.
    # Annotation finalization flips the row to COMPLETED but preserves
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

    apply_persisted_zotero_annotations(
        db=db,
        upload_job_id=uuid.UUID(job_id),
        document_id=uuid.UUID(str(paper.id)),
        user=job_user,
        page_dimensions=(),
    )

    logger.info(
        f"Finalized Zotero import for job {job_id} with paper {paper.id}"
        + (f" (worker error: {error_message})" if error_message else "")
    )
    return str(paper.id)


def handle_failed_upload(
    db: Session,
    job_id: str,
    job_user: Actor,
    *,
    operation: OperationContext,
    reason: str = "Unknown error",
) -> tuple[OperationChange, ...]:
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
        return ()

    logger.error(f"PDF processing failed for job {job_id}: {reason}")
    changes: list[OperationChange] = []

    if job and job.job.document_id is not None:
        durable_job = job.job
        document_id = durable_job.document_id
        assert document_id is not None
        document = db.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if (
            document is not None
            and document.processing_job_id == job.id
            and can_fail_processing(
                DocumentProcessingStatus(document.processing_status)
            )
        ):
            document.processing_status = DocumentProcessingStatus.FAILED.value
            document.parser_warning_code = "processing_failed"
            changes.append(
                OperationChange(
                    action=DOCUMENT_PROCESSING_FAILED,
                    resources=(ResourceRef("document", str(document_id)),),
                )
            )
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
            from app.bootstrap.adapters.document_gc import (
                schedule_document_gc,
            )

            scheduled_gc = schedule_document_gc(
                db,
                document_id=document_id,
                origin_operation_id=operation.trace.operation_id,
                correlation_id=operation.trace.correlation_id,
            )
            if scheduled_gc is not None and scheduled_gc.created:
                changes.append(
                    OperationChange(
                        action=JOB_CREATED,
                        resources=(ResourceRef("job", str(scheduled_gc.job_id)),),
                    )
                )

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
    return tuple(changes)


class SqlAlchemyPdfPostprocessReader(PdfPostprocessReader):
    """Load immutable callback facts and close the Session before providers run."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def read(
        self,
        *,
        actor: Actor,
        job_id: uuid.UUID,
        callback_task_id: uuid.UUID,
    ) -> PdfPostprocessSnapshot:
        with self._session_factory() as db:
            job = job_repository.require(db, job_id=job_id)
            if (
                job.operation != JobOperation.PDF_POSTPROCESS.value
                or callback_task_id != job_id
            ):
                raise AppError(
                    code="job_callback_mismatch",
                    message="Job callback does not match",
                    kind=FailureKind.CONFLICT,
                )
            if job.requested_by_id != actor.id:
                raise AppError(
                    code="job_requester_mismatch",
                    message="Job requester does not match callback operation",
                    kind=FailureKind.CONFLICT,
                )
            if job.status in {
                JobStatus.COMPLETED.value,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            }:
                return PdfPostprocessSnapshot(terminal=True, fields=None)
            if job.document_id is None:
                raise AppError(
                    code="job_scope_missing",
                    message="Job scope is incomplete",
                    kind=FailureKind.CONFLICT,
                )
            paper = db.get(Document, job.document_id)
            if paper is None:
                raise AppError(
                    code="job_scope_missing",
                    message="Job scope is no longer available",
                    kind=FailureKind.CONFLICT,
                )
            return PdfPostprocessSnapshot(
                terminal=False,
                fields=fields_from_paper(paper),
            )


def _apply_pdf_postprocess(
    *,
    db: Session,
    paper: Document,
    actor: Actor,
    resolution: PdfPostprocessResolution,
) -> bool:
    """Apply provider facts and search projection without external I/O."""
    if not paper.raw_content:
        raise RuntimeError("pdf_postprocess_content_missing")
    document_search_repository.replace_passage_index(
        db,
        document_id=paper.id,
        raw_content=paper.raw_content,
    )

    candidates: dict[str, object | None] = {
        "doi": resolution.doi,
        "journal": resolution.journal,
        "publisher": resolution.publisher,
        "publish_date": resolution.publish_date,
    }
    updates: dict[str, object] = {
        field_name: value
        for field_name, value in candidates.items()
        if value is not None and not getattr(paper, field_name)
    }
    if resolution.field_provenance is not None and updates:
        provenance = dict(paper.field_provenance or {})
        provenance.update(
            {
                field_name: resolution.field_provenance[field_name]
                for field_name in updates
                if field_name in resolution.field_provenance
            }
        )
        updates["field_provenance"] = provenance
    updates["attempted_metadata_at"] = datetime.now(timezone.utc)
    updated = document_repository.update_canonical(
        db,
        document=paper,
        update=DocumentUpdate.model_validate(updates),
        user=actor,
        refresh_result=False,
    )
    return bool((updated or paper).doi)


def complete_pdf_postprocess_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
    *,
    actor: Actor,
    operation: OperationContext,
    resolution: PdfPostprocessResolution,
) -> JobHandlerResult:
    job = job_repository.require(db, job_id=job_id)
    if (
        job.operation != JobOperation.PDF_POSTPROCESS.value
        or callback.task_id != job_id
    ):
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback does not match",
            kind=FailureKind.CONFLICT,
        )
    if job.status in {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }:
        return JobHandlerResult(value=JobClaimResponse(claimed=False))
    if job.document_id is None or job.requested_by_id is None:
        raise AppError(
            code="job_scope_missing",
            message="Job scope is incomplete",
            kind=FailureKind.CONFLICT,
        )
    paper = db.get(Document, job.document_id)
    if paper is None:
        raise AppError(
            code="job_scope_missing",
            message="Job scope is no longer available",
            kind=FailureKind.CONFLICT,
        )
    has_doi = _apply_pdf_postprocess(
        db=db,
        paper=paper,
        actor=actor,
        resolution=resolution,
    )
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result={"document_id": str(paper.id)},
    )
    return JobHandlerResult(
        value=JobClaimResponse(claimed=changed),
        changes=(
            (
                OperationChange(
                    action=DOCUMENT_METADATA_HYDRATED,
                    resources=(ResourceRef("document", str(paper.id)),),
                ),
            )
            if changed
            else ()
        ),
        post_commit=(
            (
                RecordJobTelemetry(
                    actor_id=actor.id,
                    event="doi_resolved",
                    properties=(("has_doi", has_doi),),
                ),
            )
            if changed
            else ()
        ),
    )


def complete_document_gc_job(
    job_id: uuid.UUID,
    callback: JobCallbackIdentity,
    db: Session,
    *,
    operation: OperationContext,
) -> JobHandlerResult:
    job = job_repository.require(db, job_id=job_id)
    if job.operation != JobOperation.DOCUMENT_GC.value or callback.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback does not match",
            kind=FailureKind.CONFLICT,
        )
    if job.status in {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }:
        return JobHandlerResult(value=JobClaimResponse(claimed=False))
    if job.document_id is None:
        _, changed = job_repository.complete(
            db,
            job_id=job_id,
            result={"deleted": True, "cancelled": False},
        )
        return JobHandlerResult(value=JobClaimResponse(claimed=changed))

    result = collect_document_if_due(
        db,
        document_id=job.document_id,
        origin_operation_id=operation.trace.operation_id,
        correlation_id=operation.trace.correlation_id,
    )
    if not result.deleted and not result.cancelled:
        raise AppError(
            code="document_gc_not_due",
            message="Document cleanup is not due",
            kind=FailureKind.UNAVAILABLE,
        )
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result={
            "deleted": result.deleted,
            "cancelled": result.cancelled,
        },
    )
    changes: list[OperationChange] = []
    if result.deleted:
        changes.append(
            OperationChange(
                action=DOCUMENT_DELETED,
                resources=(ResourceRef("document", str(result.document_id)),),
            )
        )
    if result.storage_deletion is not None and result.storage_deletion.created:
        changes.append(
            OperationChange(
                action=JOB_CREATED,
                resources=(
                    ResourceRef(
                        "job",
                        str(result.storage_deletion.job_id),
                    ),
                ),
            )
        )
    return JobHandlerResult(
        value=JobClaimResponse(claimed=changed),
        changes=tuple(changes),
    )


def complete_storage_delete_job(
    job_id: uuid.UUID,
    callback: StorageDeleteCallback,
    db: Session,
) -> JobHandlerResult:
    job = job_repository.require(db, job_id=job_id)
    if job.operation != JobOperation.STORAGE_DELETE.value or callback.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Job callback does not match",
            kind=FailureKind.CONFLICT,
        )
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result={"deleted_count": callback.deleted_count},
    )
    return JobHandlerResult(value=JobClaimResponse(claimed=changed))


def _pdf_post_commit_actions(
    *,
    actor_id: int,
    job_id: uuid.UUID,
    usage_events: list[TokenUsageEventPayload],
    telemetry: tuple[RecordJobTelemetry, ...] = (),
) -> tuple[JobPostCommitAction, ...]:
    """Return effects that must never run inside the callback database UoW."""
    return (
        SettleJobUsage(user_id=actor_id, events=tuple(usage_events)),
        ReleaseJobConcurrency(
            user_id=actor_id,
            category="background",
            job_id=job_id,
        ),
        *telemetry,
    )


def _document_change(
    *,
    action: OperationAction,
    document_id: object,
) -> OperationChange:
    return OperationChange(
        action=action,
        resources=(ResourceRef("document", str(document_id)),),
    )


def _failed_pdf_result(
    *,
    db: Session,
    job_id: str,
    actor: Actor,
    operation: OperationContext,
    reason: str,
    status: str,
    post_commit: tuple[JobPostCommitAction, ...],
) -> JobHandlerResult:
    changes = handle_failed_upload(
        db=db,
        job_id=job_id,
        job_user=actor,
        operation=operation,
        reason=reason,
    )
    return JobHandlerResult(
        value={"status": status},
        changes=changes,
        post_commit=post_commit,
    )


async def handle_paper_processing_webhook(
    job_id: str,
    webhook_data: PdfProcessingWebhookData,
    db: Session,
    *,
    actor: Actor,
    operation: OperationContext,
) -> JobHandlerResult:
    """Apply one PDF-worker result under the resumed durable-job operation."""
    upload_job = upload_reservation_repository.get_by(
        db=db,
        task_id=webhook_data.task_id,
        id=job_id,
    )
    if upload_job is None:
        raise AppError(
            code="job_not_found",
            message="Job not found",
            kind=FailureKind.NOT_FOUND,
        )

    durable_job = job_repository.require(db, job_id=upload_job.id)
    if durable_job.operation != JobOperation.PDF_PROCESS.value:
        raise AppError(
            code="job_operation_mismatch",
            message="Job operation does not match callback",
            kind=FailureKind.CONFLICT,
        )
    if durable_job.requested_by_id != actor.id:
        raise AppError(
            code="job_requester_mismatch",
            message="Job requester does not match callback operation",
            kind=FailureKind.CONFLICT,
        )

    normalized_job_id = str(upload_job.id)
    job_uuid = upload_job.id
    post_commit = _pdf_post_commit_actions(
        actor_id=actor.id,
        job_id=job_uuid,
        usage_events=webhook_data.usage_events,
    )
    if durable_job.status in {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }:
        logger.warning(
            "Ignoring late callback for terminal PDF job %s with status %s",
            normalized_job_id,
            durable_job.status,
        )
        return JobHandlerResult(
            value={"status": "webhook ignored - job is terminal"},
            post_commit=post_commit,
        )

    # A dedicated connection owns this short, non-blocking serialization lock.
    # The ApplicationExecutor remains the sole owner of the database commit.
    job_lock = AdvisoryLock(
        engine,
        namespace=AdvisoryLockNamespace.PAPER_PROCESSING_WEBHOOK,
        key=normalized_job_id,
    )
    if not job_lock.acquire():
        logger.warning(
            "PDF callback for job %s is already being processed",
            normalized_job_id,
        )
        return JobHandlerResult(
            value={"status": "webhook ignored - already being processed"}
        )

    try:
        try:
            with db.begin_nested():
                db.refresh(durable_job)
                if durable_job.status in {
                    JobStatus.COMPLETED.value,
                    JobStatus.FAILED.value,
                    JobStatus.CANCELLED.value,
                }:
                    return JobHandlerResult(
                        value={"status": "webhook ignored - job is terminal"},
                        post_commit=post_commit,
                    )

                result = webhook_data.result
                zotero_import = zotero_import_repository.get_by_upload_job_id(
                    db,
                    upload_job_id=job_uuid,
                )
                if webhook_data.status != "completed" or not result.success:
                    error_message = result.error or "Unknown error"
                    if zotero_import:
                        salvaged = _finalize_zotero_import(
                            db=db,
                            job_id=normalized_job_id,
                            job_user=actor,
                            result=result,
                            error_message=error_message,
                        )
                        if salvaged:
                            changed = _complete_pdf_job(
                                db,
                                job_id=job_uuid,
                                result=result,
                            )
                            return JobHandlerResult(
                                value={
                                    "status": "webhook processed - zotero salvage",
                                    "document_id": salvaged,
                                },
                                changes=(
                                    (
                                        _document_change(
                                            action=DOCUMENT_PROCESSING_COMPLETED,
                                            document_id=salvaged,
                                        ),
                                        OperationChange(
                                            action=ZOTERO_IMPORT_COMPLETED,
                                            resources=(
                                                ResourceRef(
                                                    "document",
                                                    str(salvaged),
                                                ),
                                            ),
                                        ),
                                    )
                                    if changed
                                    else ()
                                ),
                                post_commit=post_commit,
                            )
                    return _failed_pdf_result(
                        db=db,
                        job_id=normalized_job_id,
                        actor=actor,
                        operation=operation,
                        reason=error_message,
                        status="webhook processed - failed",
                        post_commit=post_commit,
                    )

                # Zotero supplied authoritative metadata before the worker ran.
                if zotero_import:
                    finalized = _finalize_zotero_import(
                        db=db,
                        job_id=normalized_job_id,
                        job_user=actor,
                        result=result,
                    )
                    if finalized:
                        changed = _complete_pdf_job(
                            db,
                            job_id=job_uuid,
                            result=result,
                        )
                        zotero_post_commit = _pdf_post_commit_actions(
                            actor_id=actor.id,
                            job_id=job_uuid,
                            usage_events=webhook_data.usage_events,
                            telemetry=(
                                RecordJobTelemetry(
                                    actor_id=actor.id,
                                    event="zotero_paper_processed",
                                    properties=(("worker_duration", result.duration),),
                                ),
                            ),
                        )
                        return JobHandlerResult(
                            value={
                                "status": "webhook processed - zotero import",
                                "document_id": finalized,
                            },
                            changes=(
                                (
                                    _document_change(
                                        action=DOCUMENT_PROCESSING_COMPLETED,
                                        document_id=finalized,
                                    ),
                                    OperationChange(
                                        action=ZOTERO_IMPORT_COMPLETED,
                                        resources=(
                                            ResourceRef(
                                                "document",
                                                str(finalized),
                                            ),
                                        ),
                                    ),
                                )
                                if changed
                                else ()
                            ),
                            post_commit=zotero_post_commit,
                        )
                    return _failed_pdf_result(
                        db=db,
                        job_id=normalized_job_id,
                        actor=actor,
                        operation=operation,
                        reason="Zotero import missing metadata",
                        status="webhook processed - zotero import failed",
                        post_commit=post_commit,
                    )

                metadata = result.metadata
                if metadata is None or not metadata.title:
                    logger.error(
                        "No metadata in PDF callback for job %s",
                        normalized_job_id,
                    )
                    return _failed_pdf_result(
                        db=db,
                        job_id=normalized_job_id,
                        actor=actor,
                        operation=operation,
                        reason="Missing metadata",
                        status=("webhook processed - failed due to missing metadata"),
                        post_commit=post_commit,
                    )
                if not result.raw_content:
                    logger.error(
                        "No raw content in PDF callback for job %s",
                        normalized_job_id,
                    )
                    return _failed_pdf_result(
                        db=db,
                        job_id=normalized_job_id,
                        actor=actor,
                        operation=operation,
                        reason="Missing raw_content",
                        status=(
                            "webhook processed - failed due to missing raw_content"
                        ),
                        post_commit=post_commit,
                    )

                existing_paper = document_repository.find_by_upload_job(
                    db=db,
                    upload_job_id=normalized_job_id,
                    user=actor,
                )
                if existing_paper is None:
                    raise AppError(
                        code="paper_not_found",
                        message="Paper not found",
                        kind=FailureKind.NOT_FOUND,
                    )
                if not can_complete_processing(
                    DocumentProcessingStatus(existing_paper.processing_status)
                ):
                    raise RuntimeError("document_completion_transition_rejected")
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
                        publish_date=metadata.publish_date,
                        raw_content=result.raw_content,
                        parser_markdown_s3_key=result.parser_markdown_s3_key,
                        parser_archive_s3_key=result.parser_archive_s3_key,
                        parser_backend=result.parser_backend,
                        parser_quality=result.parser_quality,
                        parser_version=result.parser_version,
                        parser_warning_code=result.parser_warning_code,
                        page_offset_map=result.page_offset_map,
                        processing_status=(DocumentProcessingStatus.COMPLETED.value),
                    ),
                    document=existing_paper,
                    user=actor,
                    refresh_result=False,
                )

                created_highlight_ids: tuple[uuid.UUID, ...] = ()
                created_comment_ids: tuple[uuid.UUID, ...] = ()
                if metadata.highlights:
                    with optional_savepoint(
                        db,
                        operation="create_ai_highlights",
                        context={
                            "job_id": normalized_job_id,
                            "document_id": str(paper.id),
                        },
                    ):
                        created_highlights = create_ai_highlights(
                            db,
                            document_id=paper.id,
                            metadata=metadata,
                            user=actor,
                        )
                        created_highlight_ids = created_highlights.thread_ids
                        created_comment_ids = created_highlights.comment_ids

                summary_conversation_id: uuid.UUID | None = None
                summary_message_id: uuid.UUID | None = None
                if metadata.summary:
                    with optional_savepoint(
                        db,
                        operation="create_summary_conversation",
                        context={
                            "job_id": normalized_job_id,
                            "document_id": str(paper.id),
                        },
                    ):
                        conversation = conversation_repository.create(
                            db,
                            request=ConversationCreateRequest(
                                scope_type=ConversationScopeType.PAPER,
                                scope_id=paper.id,
                            ),
                            user_id=actor.id,
                            refresh_result=False,
                        )
                        summary_content, references = materialize_summary_references(
                            metadata.summary,
                            metadata.summary_citations,
                            document_id=paper.id,
                            title=paper.title,
                        )
                        message = message_repository.create(
                            db,
                            request=MessageCreate(
                                conversation_id=conversation.id,
                                turn_id=operation.trace.operation_id,
                                created_operation_id=operation.trace.operation_id,
                                correlation_id=operation.trace.correlation_id,
                                role=RoleType.ASSISTANT,
                                content=summary_content,
                                references=(
                                    _JSON_OBJECT.validate_python(
                                        references.model_dump(mode="json")
                                    )
                                    if references is not None
                                    else None
                                ),
                            ),
                            user_id=actor.id,
                            refresh_result=False,
                        )
                        summary_conversation_id = conversation.id
                        summary_message_id = message.id

                completed = _complete_pdf_job(
                    db,
                    job_id=job_uuid,
                    result=result,
                )
                postprocess_job = _enqueue_pdf_postprocess(
                    db,
                    ingestion_job_id=job_uuid,
                    document_id=paper.id,
                    user_id=actor.id,
                    origin_operation_id=operation.trace.operation_id,
                    correlation_id=operation.trace.correlation_id,
                )
                changes: list[OperationChange] = []
                if completed:
                    changes.append(
                        _document_change(
                            action=DOCUMENT_PROCESSING_COMPLETED,
                            document_id=paper.id,
                        )
                    )
                changes.extend(
                    OperationChange(
                        action=RESEARCH_HIGHLIGHT_CREATED,
                        resources=(ResourceRef("research_item", str(thread_id)),),
                    )
                    for thread_id in created_highlight_ids
                )
                changes.extend(
                    OperationChange(
                        action=RESEARCH_ANNOTATION_COMMENT_CREATED,
                        resources=(
                            ResourceRef(
                                "annotation_comment",
                                str(comment_id),
                            ),
                        ),
                    )
                    for comment_id in created_comment_ids
                )
                if summary_conversation_id is not None:
                    changes.append(
                        OperationChange(
                            action=CONVERSATION_CREATED,
                            resources=(
                                ResourceRef(
                                    "conversation",
                                    str(summary_conversation_id),
                                ),
                            ),
                        )
                    )
                if summary_message_id is not None:
                    changes.append(
                        OperationChange(
                            action=CONVERSATION_MESSAGE_CREATED,
                            resources=(
                                ResourceRef(
                                    "message",
                                    str(summary_message_id),
                                ),
                            ),
                        )
                    )
                if postprocess_job.created:
                    changes.append(
                        OperationChange(
                            action=JOB_CREATED,
                            resources=(
                                ResourceRef(
                                    "job",
                                    str(postprocess_job.job.id),
                                ),
                            ),
                        )
                    )
                end_time = datetime.now(timezone.utc)
                success_post_commit = _pdf_post_commit_actions(
                    actor_id=actor.id,
                    job_id=job_uuid,
                    usage_events=webhook_data.usage_events,
                    telemetry=(
                        RecordJobTelemetry(
                            actor_id=actor.id,
                            event="extracted_metadata",
                            properties=(
                                ("has_title", bool(metadata.title)),
                                ("has_authors", bool(metadata.authors)),
                                ("has_abstract", bool(metadata.abstract)),
                                ("has_summary", bool(metadata.summary)),
                                (
                                    "has_ai_highlights",
                                    bool(metadata.highlights),
                                ),
                            ),
                        ),
                        RecordJobTelemetry(
                            actor_id=actor.id,
                            event="paper_upload",
                            properties=(
                                ("has_metadata", True),
                                (
                                    "duration",
                                    (end_time - upload_job.created_at).total_seconds(),
                                ),
                                ("worker_duration", result.duration),
                            ),
                        ),
                    ),
                )
                return JobHandlerResult(
                    value={
                        "status": "webhook processed",
                        "document_id": str(paper.id),
                    },
                    changes=tuple(changes),
                    post_commit=success_post_commit,
                )
        except Exception:
            logger.exception(
                "PDF callback application failed",
                extra={"job_id": normalized_job_id},
            )
            try:
                with db.begin_nested():
                    return _failed_pdf_result(
                        db=db,
                        job_id=normalized_job_id,
                        actor=actor,
                        operation=operation,
                        reason="webhook_processing_failed",
                        status="webhook processed - application failed",
                        post_commit=post_commit,
                    )
            except Exception as cleanup_error:
                logger.exception(
                    "PDF callback failure cleanup failed",
                    extra={"job_id": normalized_job_id},
                )
                raise AppError(
                    code="pdf_webhook_failed",
                    message="The PDF processing result could not be applied",
                    kind=FailureKind.INTERNAL,
                ) from cleanup_error
    finally:
        job_lock.release()


def schedule_zotero_jobs(
    *,
    threshold_seconds: int,
    db: Session,
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
) -> ScheduledZoteroJobs:
    """Persist one idempotent job per due and eligible Zotero user."""
    threshold_hours = threshold_seconds / 3600
    user_ids = zotero_import_repository.list_user_ids_due_for_sync(
        db, threshold_hours=threshold_hours
    )
    scheduled = 0
    skipped = 0
    created_job_ids: list[uuid.UUID] = []
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
                correlation_id=correlation_id,
                origin_operation_id=origin_operation_id,
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
        if job.created:
            scheduled += 1
            created_job_ids.append(job.job.id)
    return ScheduledZoteroJobs(
        total_users=len(user_ids),
        scheduled_jobs=scheduled,
        skipped_users=skipped,
        created_job_ids=tuple(created_job_ids),
    )
