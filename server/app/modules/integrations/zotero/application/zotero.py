"""Zotero connection, import, and synchronization use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroImportStatusListResponse,
    ZoteroLibraryResponse,
    ZoteroStatusResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.actions import (
    ZOTERO_ANNOTATIONS_SYNCED,
    ZOTERO_CONNECTION_CONNECTED,
    ZOTERO_CONNECTION_DISCONNECTED,
    ZOTERO_IMPORT_COMPLETED,
    ZOTERO_IMPORT_FAILED,
    ZOTERO_IMPORT_STARTED,
)
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationChange,
    ResourceRef,
)
from app.modules.jobs.application.actions import JOB_COMPLETED, JOB_CREATED, JOB_FAILED
from app.modules.jobs.application.jobs import (
    IdempotentOperationPort,
    ReserveOperationCommand,
)
from app.modules.integrations.zotero.domain import (
    ImportReservationAction,
    ImportReservationFacts,
    canonical_import_payload,
    decide_import_reservation,
    import_idempotency_key,
    require_zotero_connected,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.shared.domain import JsonValue
from app.shared.domain.enums import JobOperation, JobStatus
from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ZoteroGateway(Protocol):
    def save_oauth_request(
        self,
        *,
        user_id: int,
        request_token: ZoteroRequestToken,
        correlation_id: UUID,
        origin_operation_id: UUID,
    ) -> None: ...

    def oauth_callback(
        self,
        *,
        oauth_token: str,
    ) -> PreparedZoteroCallback | None: ...

    def save_connection(
        self,
        *,
        callback: PreparedZoteroCallback,
        access_token: ZoteroAccessToken,
    ) -> ZoteroConnectionChange: ...

    def status(self, *, user_id: int) -> ZoteroStatusResponse: ...

    def disconnect(self, *, user_id: int) -> UUID | None: ...

    def credentials(self, *, user_id: int) -> ZoteroCredentials | None: ...

    def library(
        self,
        *,
        actor: Actor,
        snapshot: ZoteroLibrarySnapshot,
    ) -> ZoteroLibraryResponse: ...

    def plan_import(
        self,
        *,
        actor: Actor,
        items: tuple[ZoteroItemSnapshot, ...],
    ) -> ZoteroImportPlan: ...

    def reserve_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID,
    ) -> UUID: ...

    def fail_import_item(
        self,
        *,
        user_id: int,
        item_key: str,
        upload_job_id: UUID | None,
        error_code: str,
    ) -> ZoteroItemMutation: ...

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
    ) -> ZoteroImportMutation: ...

    def link_import_item(
        self,
        *,
        actor: Actor,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        page_dimensions: PageDimensions,
    ) -> ZoteroImportMutation: ...

    def sync_targets(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> tuple[ZoteroSyncTarget, ...]: ...

    def apply_sync(
        self,
        *,
        actor: Actor,
        batch: ZoteroSyncBatch,
    ) -> ZoteroSyncMutation: ...

    def auto_import_since(self, *, user_id: int) -> datetime | None: ...

    def imports(
        self,
        *,
        user_id: int,
        item_keys: list[str] | None,
    ) -> ZoteroImportStatusListResponse: ...

    def prepare_postprocess(
        self,
        *,
        actor: Actor | None,
        job_id: UUID,
        callback_task_id: UUID,
    ) -> PreparedZoteroPostprocess: ...

    def complete_postprocess(
        self,
        *,
        job_id: UUID,
        result: ZoteroPostprocessResult,
    ) -> bool: ...

    def fail_postprocess(
        self,
        *,
        job_id: UUID,
        error_code: str,
    ) -> bool: ...


class ZoteroImportCapacity(Protocol):
    def require(self, *, actor: Actor) -> None: ...


@dataclass(frozen=True, slots=True)
class ZoteroCredentials:
    user_id: str
    api_key: str


@dataclass(frozen=True, slots=True)
class ZoteroRequestToken:
    token: str
    secret: str


@dataclass(frozen=True, slots=True)
class ZoteroAccessToken:
    user_id: str
    api_key: str


type PageDimensions = tuple[tuple[int, float, float], ...]


@dataclass(frozen=True, slots=True)
class ZoteroItemSnapshot:
    item_key: str
    title: str
    authors: tuple[str, ...]
    abstract: str | None
    publish_date: str | None
    doi: str | None
    tags: tuple[str, ...]
    date_added: str | None
    item_type: str
    venue: str | None
    collections: tuple[str, ...]
    has_pdf_attachment: bool
    has_metadata: bool


@dataclass(frozen=True, slots=True)
class ZoteroLibrarySnapshot:
    items: tuple[ZoteroItemSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ZoteroAttachmentSnapshot:
    item_key: str
    import_source: str
    attachment_key: str | None
    source_url: str | None
    annotations_json: str


@dataclass(frozen=True, slots=True)
class ZoteroImportContent:
    item: ZoteroItemSnapshot
    attachment: ZoteroAttachmentSnapshot
    pdf_content: bytes | None
    page_dimensions: PageDimensions
    error: str | None


@dataclass(frozen=True, slots=True)
class ZoteroImportPlanItem:
    item: ZoteroItemSnapshot
    disposition: Literal["import", "link_existing", "link_batch"]
    document_id: UUID | None = None
    document_source_key: str | None = None
    source_item_key: str | None = None


@dataclass(frozen=True, slots=True)
class ZoteroImportPlan:
    items: tuple[ZoteroImportPlanItem, ...]
    skipped_already_imported: int
    errors: tuple[ZoteroImportError, ...]


@dataclass(frozen=True, slots=True)
class ZoteroItemMutation:
    imported_item_id: UUID
    changed: bool


@dataclass(frozen=True, slots=True)
class ZoteroImportMutation:
    imported_item_id: UUID
    result: ZoteroImportItemResult
    changed: bool
    completed: bool


@dataclass(frozen=True, slots=True)
class ZoteroSyncTarget:
    imported_item_id: UUID
    item_key: str
    document_id: UUID
    attachment_key: str
    document_source_key: str | None


@dataclass(frozen=True, slots=True)
class ZoteroSyncUpdate:
    target: ZoteroSyncTarget
    annotations_json: str
    page_dimensions: PageDimensions


@dataclass(frozen=True, slots=True)
class ZoteroSyncBatch:
    updates: tuple[ZoteroSyncUpdate, ...]
    failed_item_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedZoteroSync:
    credentials: ZoteroCredentials
    targets: tuple[ZoteroSyncTarget, ...]


@dataclass(frozen=True, slots=True)
class ZoteroSyncMutation:
    response: ZoteroSyncResponse
    changed_document_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PreparedZoteroCallback:
    user_id: int
    request_token: ZoteroRequestToken
    expires_at: datetime
    correlation_id: UUID
    origin_operation_id: UUID


@dataclass(frozen=True, slots=True)
class ZoteroConnectionChange:
    connection_id: UUID
    changed: bool


@dataclass(frozen=True, slots=True)
class PreparedZoteroImport:
    credentials: ZoteroCredentials
    request: ZoteroImportRequest
    reservation_id: UUID | None


@dataclass(frozen=True, slots=True)
class PreparedZoteroPostprocess:
    job_id: UUID
    credentials: ZoteroCredentials | None
    disposition: Literal["run", "already_completed", "skip"]
    skip_reason: str | None = None

    def __post_init__(self) -> None:
        if self.disposition == "run":
            if self.credentials is None or self.skip_reason is not None:
                raise ValueError("runnable Zotero postprocess preparation is invalid")
            return
        if self.credentials is not None:
            raise ValueError("non-runnable Zotero postprocess cannot carry credentials")
        if self.disposition == "skip" and not self.skip_reason:
            raise ValueError("skipped Zotero postprocess requires a reason")
        if self.disposition == "already_completed" and self.skip_reason is not None:
            raise ValueError("completed Zotero postprocess cannot carry a skip reason")


@dataclass(frozen=True, slots=True)
class ZoteroPostprocessResult:
    synced_papers_count: int
    new_annotations_count: int
    auto_imported_count: int
    skipped_reason: str | None = None

    def __post_init__(self) -> None:
        if (
            min(
                self.synced_papers_count,
                self.new_annotations_count,
                self.auto_imported_count,
            )
            < 0
        ):
            raise ValueError("Zotero postprocess counts cannot be negative")


class Zotero:
    def __init__(
        self,
        *,
        gateway: ZoteroGateway,
        capacity: ZoteroImportCapacity,
        idempotency: IdempotentOperationPort,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._idempotency = idempotency
        self._journal = journal

    def save_oauth_request(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request_token: ZoteroRequestToken,
        auth_url: str,
    ) -> ZoteroConnectResponse:
        self._gateway.save_oauth_request(
            user_id=actor.id,
            request_token=request_token,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
        )
        return ZoteroConnectResponse(auth_url=auth_url)

    def prepare_oauth_callback(
        self,
        *,
        oauth_token: str,
        now: datetime,
    ) -> PreparedZoteroCallback | None:
        callback = self._gateway.oauth_callback(
            oauth_token=oauth_token,
        )
        if callback is None:
            return None
        if callback.expires_at < now:
            return None
        return callback

    def complete_oauth_callback(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        callback: PreparedZoteroCallback,
        access_token: ZoteroAccessToken,
    ) -> bool:
        if actor.id != callback.user_id:
            raise AppError(
                code="zotero_callback_owner_mismatch",
                message="Zotero callback ownership could not be verified",
                kind=FailureKind.PERMISSION_DENIED,
            )
        change = self._gateway.save_connection(
            callback=callback,
            access_token=access_token,
        )
        if change.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_CONNECTION_CONNECTED,
                resources=(
                    ResourceRef("zotero_connection", str(change.connection_id)),
                ),
            )
        return True

    def status(self, *, actor: Actor) -> ZoteroStatusResponse:
        return self._gateway.status(user_id=actor.id)

    def disconnect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> None:
        connection_id = self._gateway.disconnect(user_id=actor.id)
        if connection_id is not None:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_CONNECTION_DISCONNECTED,
                resources=(ResourceRef("zotero_connection", str(connection_id)),),
            )

    def prepare_library(self, *, actor: Actor) -> ZoteroCredentials:
        return self._require_credentials(actor)

    def library(
        self,
        *,
        actor: Actor,
        snapshot: ZoteroLibrarySnapshot,
    ) -> ZoteroLibraryResponse:
        return self._gateway.library(actor=actor, snapshot=snapshot)

    def prepare_import_batch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ZoteroImportRequest,
        idempotency_key: str | None,
    ) -> ZoteroImportResponse | PreparedZoteroImport:
        credentials = self._require_credentials(actor)
        self._capacity.require(actor=actor)

        reservation_id = None
        if idempotency_key:
            reservation_id = uuid4()
            request_payload = canonical_import_payload(request.item_keys)
            reserved = self._idempotency.reserve(
                command=ReserveOperationCommand(
                    operation_id=reservation_id,
                    operation=JobOperation.ZOTERO_IMPORT,
                    requested_by_id=actor.id,
                    correlation_id=operation.trace.correlation_id,
                    origin_operation_id=operation.trace.operation_id,
                    idempotency_key=import_idempotency_key(
                        actor_id=actor.id,
                        request_key=idempotency_key,
                    ),
                    payload=request_payload,
                )
            )
            action = decide_import_reservation(
                ImportReservationFacts(
                    created=reserved.created,
                    payload_matches=reserved.payload == request_payload,
                    status=JobStatus(reserved.job.status),
                    result=reserved.job.result,
                )
            )
            if action is ImportReservationAction.REPLAY:
                assert reserved.job.result is not None
                return ZoteroImportResponse.model_validate(reserved.job.result)
            if reserved.created:
                self._journal.append(
                    actor=actor,
                    operation=operation,
                    action=JOB_CREATED,
                    resources=(ResourceRef("job", str(reservation_id)),),
                )

        return PreparedZoteroImport(
            credentials=credentials,
            request=request,
            reservation_id=reservation_id,
        )

    def plan_import(
        self,
        *,
        actor: Actor,
        items: tuple[ZoteroItemSnapshot, ...],
    ) -> ZoteroImportPlan:
        return self._gateway.plan_import(actor=actor, items=items)

    def reserve_import_item(
        self,
        *,
        actor: Actor,
        item_key: str,
        upload_job_id: UUID,
    ) -> UUID:
        return self._gateway.reserve_import_item(
            user_id=actor.id,
            item_key=item_key,
            upload_job_id=upload_job_id,
        )

    def fail_import_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item_key: str,
        upload_job_id: UUID | None,
        error_code: str,
    ) -> None:
        change = self._gateway.fail_import_item(
            user_id=actor.id,
            item_key=item_key,
            upload_job_id=upload_job_id,
            error_code=error_code,
        )
        if change.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_IMPORT_FAILED,
                resources=(ResourceRef("zotero_import", str(change.imported_item_id)),),
            )

    def complete_import_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        upload_job_id: UUID,
        document_id: UUID,
        reused_document: bool,
        page_dimensions: PageDimensions,
    ) -> ZoteroImportItemResult:
        change = self._gateway.complete_import_item(
            actor=actor,
            item=item,
            attachment=attachment,
            upload_job_id=upload_job_id,
            document_id=document_id,
            reused_document=reused_document,
            page_dimensions=page_dimensions,
        )
        self._record_import_change(
            actor=actor,
            operation=operation,
            change=change,
            document_id=document_id,
            upload_job_id=upload_job_id,
        )
        return change.result

    def link_import_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item: ZoteroItemSnapshot,
        attachment: ZoteroAttachmentSnapshot,
        document_id: UUID,
        page_dimensions: PageDimensions,
    ) -> ZoteroImportItemResult:
        change = self._gateway.link_import_item(
            actor=actor,
            item=item,
            attachment=attachment,
            document_id=document_id,
            page_dimensions=page_dimensions,
        )
        self._record_import_change(
            actor=actor,
            operation=operation,
            change=change,
            document_id=document_id,
            upload_job_id=None,
        )
        return change.result

    def complete_import_batch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedZoteroImport,
        result: ZoteroImportResponse,
    ) -> ZoteroImportResponse:
        if prepared.reservation_id is not None:
            self._idempotency.complete(
                operation_id=prepared.reservation_id,
                result=_JSON_OBJECT.validate_python(result.model_dump(mode="json")),
            )
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_COMPLETED,
                resources=(ResourceRef("job", str(prepared.reservation_id)),),
            )
        return result

    def fail_import_batch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedZoteroImport,
        error_code: str,
    ) -> None:
        if prepared.reservation_id is not None:
            self._idempotency.fail(
                operation_id=prepared.reservation_id,
                error_code=error_code,
            )
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_FAILED,
                resources=(ResourceRef("job", str(prepared.reservation_id)),),
            )

    def prepare_sync(self, *, actor: Actor) -> PreparedZoteroSync:
        return PreparedZoteroSync(
            credentials=self._require_credentials(actor),
            targets=self._gateway.sync_targets(user_id=actor.id, limit=50),
        )

    def complete_sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        batch: ZoteroSyncBatch,
    ) -> ZoteroSyncResponse:
        mutation = self._gateway.apply_sync(actor=actor, batch=batch)
        if mutation.changed_document_ids:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=ZOTERO_ANNOTATIONS_SYNCED,
                resources=tuple(
                    ResourceRef("document", str(document_id))
                    for document_id in mutation.changed_document_ids
                ),
            )
        return mutation.response

    def auto_import_since(self, *, actor: Actor) -> datetime | None:
        return self._gateway.auto_import_since(user_id=actor.id)

    def imports(
        self,
        *,
        actor: Actor,
        item_keys: list[str] | None,
    ) -> ZoteroImportStatusListResponse:
        return self._gateway.imports(user_id=actor.id, item_keys=item_keys)

    def prepare_postprocess(
        self,
        *,
        actor: Actor | None,
        job_id: UUID,
        callback_task_id: UUID,
    ) -> PreparedZoteroPostprocess:
        return self._gateway.prepare_postprocess(
            actor=actor,
            job_id=job_id,
            callback_task_id=callback_task_id,
        )

    def complete_postprocess(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        prepared: PreparedZoteroPostprocess,
        result: ZoteroPostprocessResult,
    ) -> bool:
        if prepared.disposition == "already_completed":
            return False
        changed = self._gateway.complete_postprocess(
            job_id=prepared.job_id,
            result=result,
        )
        if not changed:
            return False
        changes = [
            OperationChange(
                action=JOB_COMPLETED,
                resources=(ResourceRef("job", str(prepared.job_id)),),
            )
        ]
        if result.new_annotations_count > 0:
            changes.append(
                OperationChange(
                    action=ZOTERO_ANNOTATIONS_SYNCED,
                    resources=(ResourceRef("job", str(prepared.job_id)),),
                )
            )
        if result.auto_imported_count > 0:
            changes.append(
                OperationChange(
                    action=ZOTERO_IMPORT_STARTED,
                    resources=(ResourceRef("job", str(prepared.job_id)),),
                )
            )
        self._journal.append_many(
            actor=actor,
            operation=operation,
            changes=changes,
        )
        return True

    def fail_postprocess(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        error_code: str,
    ) -> bool:
        changed = self._gateway.fail_postprocess(
            job_id=job_id,
            error_code=error_code,
        )
        if changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=JOB_FAILED,
                resources=(ResourceRef("job", str(job_id)),),
            )
        return changed

    def _record_import_change(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        change: ZoteroImportMutation,
        document_id: UUID,
        upload_job_id: UUID | None,
    ) -> None:
        if not change.changed:
            return
        resources = [
            ResourceRef("document", str(document_id)),
            ResourceRef("zotero_import", str(change.imported_item_id)),
        ]
        if upload_job_id is not None:
            resources.append(ResourceRef("job", str(upload_job_id)))
        self._journal.append(
            actor=actor,
            operation=operation,
            action=(
                ZOTERO_IMPORT_COMPLETED if change.completed else ZOTERO_IMPORT_STARTED
            ),
            resources=tuple(resources),
        )

    def _require_credentials(self, actor: Actor) -> ZoteroCredentials:
        credentials = self._gateway.credentials(user_id=actor.id)
        require_zotero_connected(connected=credentials is not None)
        assert credentials is not None
        return credentials
