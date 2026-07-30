"""SQLAlchemy gateway for Zotero connection and import state."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from uuid import UUID

from app.bootstrap.adapters.zotero_annotations import apply_annotation_snapshot
from app.database.models import Document, ZoteroImportSource, ZoteroImportStatus
from app.helpers.paper_search import normalize_doi
from app.modules.billing.infrastructure.quotas import (
    can_user_auto_sync_zotero,
    can_user_upload_paper,
    get_remaining_paper_upload_slots,
)
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportStatusItem,
    ZoteroImportStatusListResponse,
    ZoteroLibraryItem,
    ZoteroLibraryResponse,
    ZoteroStatusResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.infrastructure.connection_repository import (
    zotero_connection_repository,
)
from app.modules.integrations.zotero.infrastructure.import_repository import (
    zotero_import_repository,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroCallback,
    PreparedZoteroPostprocess,
    PageDimensions,
    ZoteroAccessToken,
    ZoteroAttachmentSnapshot,
    ZoteroConnectionChange,
    ZoteroCredentials,
    ZoteroImportMutation,
    ZoteroImportPlan,
    ZoteroImportPlanItem,
    ZoteroItemMutation,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
    ZoteroPostprocessResult,
    ZoteroRequestToken,
    ZoteroSyncBatch,
    ZoteroSyncMutation,
    ZoteroSyncTarget,
)
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.papers.application.contracts.documents import DocumentUpdate
from app.modules.papers.infrastructure.repository import document_repository
from app.modules.papers.infrastructure.tag_repository import library_tag_repository
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain import JsonValue
from app.shared.domain.enums import JobOperation, JobStatus
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

_ANNOTATIONS = TypeAdapter(list[dict[str, JsonValue]])


class DefaultZoteroGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save_oauth_request(
        self,
        *,
        user_id: int,
        request_token: ZoteroRequestToken,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> None:
        zotero_connection_repository.delete_pending_for_user(
            db=self._db,
            user_id=user_id,
        )
        zotero_connection_repository.create_pending(
            db=self._db,
            user_id=user_id,
            oauth_token=request_token.token,
            oauth_token_secret=request_token.secret,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
        )

    def oauth_callback(
        self,
        *,
        oauth_token: str,
    ) -> PreparedZoteroCallback | None:
        pending = zotero_connection_repository.get_pending_by_token(
            db=self._db,
            oauth_token=oauth_token,
        )
        if pending is None or pending.user_id is None:
            return None
        expires_at = pending.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return PreparedZoteroCallback(
            user_id=pending.user_id,
            request_token=ZoteroRequestToken(
                token=oauth_token,
                secret=pending.oauth_token_secret,
            ),
            expires_at=expires_at,
            correlation_id=pending.correlation_id,
            origin_operation_id=pending.origin_operation_id,
        )

    def _discard_oauth_callback(self, *, oauth_token: str) -> None:
        pending = zotero_connection_repository.get_pending_by_token(
            db=self._db,
            oauth_token=oauth_token,
        )
        if pending is not None:
            zotero_connection_repository.delete_pending(
                db=self._db,
                pending=pending,
            )

    def save_connection(
        self,
        *,
        callback: PreparedZoteroCallback,
        access_token: ZoteroAccessToken,
    ) -> ZoteroConnectionChange:
        upsert = zotero_connection_repository.upsert_connection(
            db=self._db,
            user_id=callback.user_id,
            zotero_user_id=access_token.user_id,
            api_key=access_token.api_key,
        )
        self._discard_oauth_callback(
            oauth_token=callback.request_token.token,
        )
        return ZoteroConnectionChange(
            connection_id=upsert.connection.id,
            changed=upsert.changed,
        )

    def status(self, *, user_id: int) -> ZoteroStatusResponse:
        connection = zotero_connection_repository.get_by_user_id(
            db=self._db,
            user_id=user_id,
        )
        if connection is None:
            return ZoteroStatusResponse(connected=False)
        return ZoteroStatusResponse(
            connected=True,
            connected_at=connection.created_at,
            last_synced_at=zotero_import_repository.get_max_last_synced_at(
                self._db,
                user_id=user_id,
            ),
        )

    def disconnect(self, *, user_id: int) -> UUID | None:
        return zotero_connection_repository.delete_by_user_id(
            db=self._db,
            user_id=user_id,
        )

    def credentials(self, *, user_id: int) -> ZoteroCredentials | None:
        connection = zotero_connection_repository.get_by_user_id(
            self._db,
            user_id=user_id,
        )
        if connection is None:
            return None
        return ZoteroCredentials(
            user_id=str(connection.zotero_user_id),
            api_key=str(connection.api_key),
        )

    def library(
        self,
        *,
        actor: Actor,
        snapshot: ZoteroLibrarySnapshot,
    ) -> ZoteroLibraryResponse:
        imported_keys = zotero_import_repository.completed_item_keys(
            self._db,
            user_id=actor.id,
        )
        return ZoteroLibraryResponse(
            items=[
                ZoteroLibraryItem(
                    zotero_item_key=item.item_key,
                    title=item.title,
                    authors=list(item.authors),
                    date=item.publish_date,
                    item_type=item.item_type,
                    venue=item.venue,
                    date_added=item.date_added,
                    tags=list(item.tags),
                    collections=list(item.collections),
                    already_imported=item.item_key in imported_keys,
                    has_pdf_attachment=item.has_pdf_attachment,
                    has_metadata=item.has_metadata,
                )
                for item in snapshot.items
            ],
            remaining_slots=get_remaining_paper_upload_slots(
                self._db,
                actor,
            ),
        )

    def plan_import(
        self,
        *,
        actor: Actor,
        items: tuple[ZoteroItemSnapshot, ...],
    ) -> ZoteroImportPlan:
        can_upload, upload_error = can_user_upload_paper(self._db, actor)
        remaining = (
            get_remaining_paper_upload_slots(self._db, actor) if can_upload else 0
        )
        plans: list[ZoteroImportPlanItem] = []
        errors: list[ZoteroImportError] = []
        skipped = 0
        claimed_doi: dict[str, str] = {}
        candidate_count = 0

        for item in items:
            if not item.has_metadata:
                continue
            existing = zotero_import_repository.get_by_item_key(
                self._db,
                user_id=actor.id,
                zotero_item_key=item.item_key,
            )
            if (
                existing is not None
                and existing.status == ZoteroImportStatus.COMPLETED
                and existing.document_id is not None
                and document_repository.find_accessible(
                    self._db,
                    document_id=existing.document_id,
                    user=actor,
                )
                is not None
            ):
                skipped += 1
                continue

            doi = normalize_doi(item.doi)
            if doi:
                document = document_repository.find_library_document_by_doi(
                    self._db,
                    user_id=actor.id,
                    doi=doi,
                )
                if document is not None:
                    plans.append(
                        ZoteroImportPlanItem(
                            item=item,
                            disposition="link_existing",
                            document_id=document.id,
                            document_source_key=document.s3_object_key,
                        )
                    )
                    skipped += 1
                    continue
                source_item_key = claimed_doi.get(doi)
                if source_item_key is not None:
                    plans.append(
                        ZoteroImportPlanItem(
                            item=item,
                            disposition="link_batch",
                            source_item_key=source_item_key,
                        )
                    )
                    skipped += 1
                    continue

            if candidate_count >= remaining:
                errors.append(
                    ZoteroImportError(
                        zotero_item_key=item.item_key,
                        error=upload_error or "Upload limit",
                    )
                )
                continue
            plans.append(ZoteroImportPlanItem(item=item, disposition="import"))
            candidate_count += 1
            if doi:
                claimed_doi[doi] = item.item_key

        return ZoteroImportPlan(
            items=tuple(plans),
            skipped_already_imported=skipped,
            errors=tuple(errors),
        )

    def reserve_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID,
    ) -> UUID:
        existing = zotero_import_repository.get_by_item_key(
            self._db,
            user_id=user_id,
            zotero_item_key=item_key,
        )
        if existing is not None:
            if (
                existing.status == ZoteroImportStatus.COMPLETED
                and existing.document_id is not None
            ):
                raise AppError(
                    code="zotero_item_already_imported",
                    message="The Zotero item has already been imported",
                    kind=FailureKind.CONFLICT,
                )
            self._db.delete(existing)
            self._db.flush()
        created = zotero_import_repository.create(
            self._db,
            user_id=user_id,
            zotero_item_key=item_key,
            import_source=ZoteroImportSource.PDF_ATTACHMENT,
            upload_job_id=upload_job_id,
            status=ZoteroImportStatus.PROCESSING,
        )
        return created.id

    def fail_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID | None,
        error_code: str,
    ) -> ZoteroItemMutation:
        imported_item = (
            zotero_import_repository.get_by_upload_job_id(
                self._db,
                upload_job_id=upload_job_id,
            )
            if upload_job_id is not None
            else None
        )
        if imported_item is None:
            imported_item = zotero_import_repository.get_by_item_key(
                self._db,
                user_id=user_id,
                zotero_item_key=item_key,
            )
        if imported_item is None:
            imported_item = zotero_import_repository.create(
                self._db,
                user_id=user_id,
                zotero_item_key=item_key,
                import_source=ZoteroImportSource.PDF_ATTACHMENT,
                upload_job_id=upload_job_id,
                status=ZoteroImportStatus.FAILED,
            )
            imported_item.error_message = error_code
            self._db.flush()
            return ZoteroItemMutation(
                imported_item_id=imported_item.id,
                changed=True,
            )
        if imported_item.user_id != user_id:
            raise AppError(
                code="zotero_import_access_denied",
                message="Zotero import access denied",
                kind=FailureKind.PERMISSION_DENIED,
            )
        change = zotero_import_repository.update_status(
            self._db,
            item=imported_item,
            status=ZoteroImportStatus.FAILED,
            error_message=error_code,
        )
        return ZoteroItemMutation(
            imported_item_id=imported_item.id,
            changed=change.changed,
        )

    def complete_import_item(
        self,
        *,
        actor: Actor,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        upload_job_id: UUID,
        document_id: UUID,
        reused_document: bool,
        page_dimensions: PageDimensions,
    ) -> ZoteroImportMutation:
        imported_item = zotero_import_repository.get_by_upload_job_id(
            self._db,
            upload_job_id=upload_job_id,
        )
        if imported_item is None or imported_item.user_id != actor.id:
            raise AppError(
                code="zotero_import_not_found",
                message="Zotero import not found",
                kind=FailureKind.NOT_FOUND,
            )
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        if document is None:
            raise RuntimeError("zotero_canonical_document_missing")
        self._apply_metadata(document=document, item=item, actor=actor)
        self._apply_tags(document_id=document_id, tags=item.tags, actor=actor)
        annotations = self._annotations(attachment.annotations_json)
        finalized = zotero_import_repository.finalize_processing_import(
            self._db,
            item=imported_item,
            import_source=attachment.import_source,
            zotero_attachment_key=attachment.attachment_key,
            source_url=attachment.source_url,
            document_id=document_id,
            upload_job_id=upload_job_id,
            annotations_payload=annotations or None,
        )
        completed = reused_document
        changed = finalized.changed
        if reused_document:
            applied = (
                apply_annotation_snapshot(
                    self._db,
                    document_id=document_id,
                    user=actor,
                    annotations_payload=annotations,
                    page_dimensions=page_dimensions,
                )
                if annotations
                else 0
            )
            status = zotero_import_repository.update_status(
                self._db,
                item=imported_item,
                status=ZoteroImportStatus.COMPLETED,
                document_id=document_id,
            )
            changed = changed or status.changed or applied > 0
        return ZoteroImportMutation(
            imported_item_id=imported_item.id,
            result=self._import_result(
                item=item,
                attachment=attachment,
                document_id=document_id,
                upload_job_id=upload_job_id,
            ),
            changed=changed,
            completed=completed,
        )

    def link_import_item(
        self,
        *,
        actor: Actor,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        page_dimensions: PageDimensions,
    ) -> ZoteroImportMutation:
        document = document_repository.find_accessible(
            self._db,
            document_id=document_id,
            user=actor,
        )
        if document is None:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        existing = zotero_import_repository.get_by_item_key(
            self._db,
            user_id=actor.id,
            zotero_item_key=item.item_key,
        )
        if (
            existing is not None
            and existing.status == ZoteroImportStatus.COMPLETED
            and existing.document_id == document_id
        ):
            return ZoteroImportMutation(
                imported_item_id=existing.id,
                result=self._import_result(
                    item=item,
                    attachment=attachment,
                    document_id=document_id,
                    upload_job_id=None,
                ),
                changed=False,
                completed=True,
            )
        if existing is not None:
            self._db.delete(existing)
            self._db.flush()
        annotations = self._annotations(attachment.annotations_json)
        imported_item = zotero_import_repository.create(
            self._db,
            user_id=actor.id,
            zotero_item_key=item.item_key,
            import_source=attachment.import_source,
            zotero_attachment_key=attachment.attachment_key,
            source_url=attachment.source_url,
            document_id=document_id,
            annotations_payload=annotations or None,
            status=ZoteroImportStatus.COMPLETED,
            last_synced_at=datetime.now(timezone.utc),
        )
        if annotations:
            apply_annotation_snapshot(
                self._db,
                document_id=document_id,
                user=actor,
                annotations_payload=annotations,
                page_dimensions=page_dimensions,
            )
        return ZoteroImportMutation(
            imported_item_id=imported_item.id,
            result=self._import_result(
                item=item,
                attachment=attachment,
                document_id=document_id,
                upload_job_id=None,
            ),
            changed=True,
            completed=True,
        )

    def sync_targets(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[ZoteroSyncTarget, ...]:
        return tuple(
            ZoteroSyncTarget(
                imported_item_id=row.id,
                item_key=row.zotero_item_key,
                document_id=row.document_id,
                attachment_key=row.zotero_attachment_key,
                document_source_key=document.s3_object_key,
            )
            for row in zotero_import_repository.list_syncable_by_user(
                self._db,
                user_id=user_id,
                limit=limit,
            )
            if row.document_id is not None
            and row.zotero_attachment_key is not None
            and (document := self._db.get(Document, row.document_id)) is not None
        )

    def apply_sync(
        self,
        *,
        actor: Actor,
        batch: ZoteroSyncBatch,
    ) -> ZoteroSyncMutation:
        synced_documents: set[UUID] = set()
        changed_documents: set[UUID] = set()
        new_annotations = 0
        synced_at = datetime.now(timezone.utc)
        for update in batch.updates:
            target = update.target
            imported_item = zotero_import_repository.get_by_item_key(
                self._db,
                user_id=actor.id,
                zotero_item_key=target.item_key,
            )
            if (
                imported_item is None
                or imported_item.id != target.imported_item_id
                or imported_item.document_id != target.document_id
            ):
                continue
            document = document_repository.find_accessible(
                self._db,
                document_id=target.document_id,
                user=actor,
            )
            if document is None:
                continue
            annotations = self._annotations(update.annotations_json)
            applied = (
                apply_annotation_snapshot(
                    self._db,
                    document_id=target.document_id,
                    user=actor,
                    annotations_payload=annotations,
                    page_dimensions=update.page_dimensions,
                )
                if annotations
                else 0
            )
            zotero_import_repository.update_after_sync(
                self._db,
                item=imported_item,
                annotations_payload=annotations or None,
                last_synced_at=synced_at,
            )
            synced_documents.add(target.document_id)
            new_annotations += applied
            if applied:
                changed_documents.add(target.document_id)
        return ZoteroSyncMutation(
            response=ZoteroSyncResponse(
                synced_papers_count=len(synced_documents),
                new_annotations_count=new_annotations,
            ),
            changed_document_ids=tuple(sorted(changed_documents, key=str)),
        )

    def auto_import_since(self, *, user_id: int) -> datetime | None:
        return zotero_import_repository.get_auto_import_since(
            self._db,
            user_id=user_id,
        )

    def imports(
        self,
        *,
        user_id: int,
        item_keys: list[str] | None,
    ) -> ZoteroImportStatusListResponse:
        rows = (
            zotero_import_repository.list_by_item_keys(
                self._db,
                user_id=user_id,
                item_keys=item_keys,
            )
            if item_keys
            else zotero_import_repository.list_recent_by_user(
                self._db,
                user_id=user_id,
            )
        )
        return ZoteroImportStatusListResponse(
            items=[
                ZoteroImportStatusItem(
                    zotero_item_key=row.zotero_item_key,
                    document_id=str(row.document_id) if row.document_id else None,
                    upload_job_id=(
                        str(row.upload_job_id) if row.upload_job_id else None
                    ),
                    import_source=row.import_source,
                    status=row.status,
                    title=title,
                    error_message=row.error_message,
                    created_at=row.created_at,
                    last_synced_at=row.last_synced_at,
                )
                for row, title in rows
            ]
        )

    def _apply_metadata(
        self,
        *,
        document: Document,
        item: ZoteroItemSnapshot,
        actor: Actor,
    ) -> None:
        document_repository.update_canonical(
            self._db,
            document=document,
            update=DocumentUpdate(
                title=item.title or None,
                authors=list(item.authors) or None,
                abstract=item.abstract,
                publish_date=item.publish_date,
                doi=item.doi,
            ),
            user=actor,
        )

    def _apply_tags(
        self,
        *,
        document_id: UUID,
        tags: tuple[str, ...],
        actor: Actor,
    ) -> None:
        for name in tags:
            tag = library_tag_repository.get_or_create(
                self._db,
                user_id=actor.id,
                name=name,
            )
            library_tag_repository.assign_to_document(
                self._db,
                user_id=actor.id,
                document_id=document_id,
                tag_id=tag.id,
            )

    @staticmethod
    def _annotations(value: str) -> list[dict[str, JsonValue]]:
        if not value:
            return []
        return _ANNOTATIONS.validate_python(json.loads(value))

    @staticmethod
    def _import_result(
        *,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        upload_job_id: UUID | None,
    ) -> ZoteroImportItemResult:
        return ZoteroImportItemResult(
            zotero_item_key=item.item_key,
            document_id=str(document_id),
            upload_job_id=str(upload_job_id) if upload_job_id is not None else None,
            import_source=attachment.import_source,
            title=item.title or None,
        )

    def prepare_postprocess(
        self,
        *,
        actor: Actor | None,
        job_id: UUID,
        callback_task_id: UUID,
    ) -> PreparedZoteroPostprocess:
        job = job_repository.require(self._db, job_id=job_id)
        if (
            job.operation != JobOperation.ZOTERO_POSTPROCESS.value
            or callback_task_id != job_id
        ):
            raise AppError(
                code="job_callback_mismatch",
                message="Job callback does not match",
                kind=FailureKind.CONFLICT,
            )
        if JobStatus(job.status) in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }:
            return PreparedZoteroPostprocess(
                job_id=job_id,
                credentials=None,
                disposition="already_completed",
            )
        actor_id = actor.id if actor is not None else None
        if actor_id != job.requested_by_id:
            raise AppError(
                code="job_owner_mismatch",
                message="Job ownership could not be verified",
                kind=FailureKind.PERMISSION_DENIED,
            )
        if actor is None:
            return PreparedZoteroPostprocess(
                job_id=job_id,
                credentials=None,
                disposition="skip",
                skip_reason="user_not_found",
            )
        connection = zotero_connection_repository.get_by_user_id(
            self._db,
            user_id=actor.id,
        )
        if not can_user_auto_sync_zotero(self._db, actor) or connection is None:
            return PreparedZoteroPostprocess(
                job_id=job_id,
                credentials=None,
                disposition="skip",
                skip_reason="not_eligible_or_disconnected",
            )
        return PreparedZoteroPostprocess(
            job_id=job_id,
            credentials=ZoteroCredentials(
                user_id=str(connection.zotero_user_id),
                api_key=str(connection.api_key),
            ),
            disposition="run",
        )

    def complete_postprocess(
        self,
        *,
        job_id: UUID,
        result: ZoteroPostprocessResult,
    ) -> bool:
        _job, changed = job_repository.complete(
            self._db,
            job_id=job_id,
            result={
                "synced_papers_count": result.synced_papers_count,
                "new_annotations_count": result.new_annotations_count,
                "auto_imported_count": result.auto_imported_count,
                **(
                    {"skipped": result.skipped_reason}
                    if result.skipped_reason is not None
                    else {}
                ),
            },
        )
        return changed

    def fail_postprocess(
        self,
        *,
        job_id: UUID,
        error_code: str,
    ) -> bool:
        _job, changed = job_repository.fail(
            self._db,
            job_id=job_id,
            error_code=error_code,
        )
        return changed
