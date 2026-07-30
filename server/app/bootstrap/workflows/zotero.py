"""Short-transaction orchestration for Zotero provider workflows."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroImportError,
    ZoteroImportItemResult,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroLibraryResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.zotero import (
    PageDimensions,
    PreparedZoteroCallback,
    PreparedZoteroImport,
    PreparedZoteroPostprocess,
    PreparedZoteroSync,
    ZoteroAccessToken,
    ZoteroAttachmentSnapshot,
    ZoteroCredentials,
    ZoteroImportContent,
    ZoteroImportPlan,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
    ZoteroPostprocessResult,
    ZoteroRequestToken,
    ZoteroSyncBatch,
    ZoteroSyncTarget,
)
from app.modules.jobs.application.contracts import (
    JobCallbackIdentity,
    JobClaimResponse,
)
from app.modules.papers.application.ingestion import (
    IngestionFinalization,
    IngestionReservation,
    IngestPaper,
    PreparedPaperInput,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OAuthCallbackOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind

logger = logging.getLogger(__name__)


class ZoteroOperations(Protocol):
    def request_token(self) -> ZoteroRequestToken | None: ...

    def authorize_url(self, *, request_token: ZoteroRequestToken) -> str: ...

    def exchange_access_token(
        self,
        *,
        callback: PreparedZoteroCallback,
        verifier: str,
    ) -> ZoteroAccessToken | None: ...

    def fetch_library(
        self,
        *,
        credentials: ZoteroCredentials,
        limit: int = 100,
    ) -> ZoteroLibrarySnapshot: ...

    def fetch_items(
        self,
        *,
        credentials: ZoteroCredentials,
        item_keys: tuple[str, ...],
    ) -> tuple[ZoteroItemSnapshot, ...]: ...

    async def fetch_import_content(
        self,
        *,
        credentials: ZoteroCredentials,
        item: ZoteroItemSnapshot,
    ) -> ZoteroImportContent: ...

    async def fetch_attachment(
        self,
        *,
        credentials: ZoteroCredentials,
        item: ZoteroItemSnapshot,
    ) -> ZoteroAttachmentSnapshot: ...

    async def fetch_page_dimensions(
        self,
        *,
        source_key: str | None,
    ) -> PageDimensions: ...

    async def fetch_sync_batch(
        self,
        *,
        credentials: ZoteroCredentials,
        targets: tuple[ZoteroSyncTarget, ...],
    ) -> ZoteroSyncBatch: ...

    async def upload_pdf(self, *, content: bytes) -> None: ...

    def record_event(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object],
    ) -> None: ...

    def parse_date_added(self, value: str | None) -> datetime | None: ...


class ZoteroWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        operations: ZoteroOperations,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._operations = operations
        self._operation_factory = operation_factory

    def connect(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> ZoteroConnectResponse:
        request_token = self._operations.request_token()
        if request_token is None:
            raise AppError(
                code="zotero_connection_failed",
                message="Zotero authorization is temporarily unavailable",
                kind=FailureKind.DEPENDENCY_FAILURE,
            )
        auth_url = self._operations.authorize_url(request_token=request_token)
        return self._executor.command(
            lambda capabilities: capabilities.zotero.save_oauth_request(
                actor=actor,
                operation=operation,
                request_token=request_token,
                auth_url=auth_url,
            )
        )

    def callback(
        self,
        *,
        oauth_token: str,
        oauth_verifier: str,
        request: RequestReference,
    ) -> bool:
        callback = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_oauth_callback(
                oauth_token=oauth_token,
                now=datetime.now(UTC),
            )
        )
        if callback is None:
            return False
        access_token = self._operations.exchange_access_token(
            callback=callback,
            verifier=oauth_verifier,
        )
        if access_token is None:
            return False
        actor = self._executor.query(
            lambda capabilities: capabilities.identity.resolve_actor_by_user_id(
                callback.user_id
            )
        )
        operation = self._operation_factory.resume(
            correlation_id=callback.correlation_id,
            causation_id=callback.origin_operation_id,
            initiated_by=OperationInitiator.SYSTEM,
            origin=OAuthCallbackOrigin(request=request, provider="zotero"),
            credential=None,
        )
        return self._executor.command(
            lambda capabilities: capabilities.zotero.complete_oauth_callback(
                actor=actor,
                operation=operation,
                callback=callback,
                access_token=access_token,
            )
        )

    async def import_items(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ZoteroImportRequest,
        idempotency_key: str | None,
    ) -> ZoteroImportResponse:
        prepared = self._executor.command(
            lambda capabilities: capabilities.zotero.prepare_import_batch(
                actor=actor,
                operation=operation,
                request=request,
                idempotency_key=idempotency_key,
            )
        )
        if isinstance(prepared, ZoteroImportResponse):
            return prepared
        try:
            items = self._operations.fetch_items(
                credentials=prepared.credentials,
                item_keys=tuple(prepared.request.item_keys),
            )
            plan = self._executor.query(
                lambda capabilities: capabilities.zotero.plan_import(
                    actor=actor,
                    items=items,
                )
            )
            result = await _execute_import_plan(
                executor=self._executor,
                operations=self._operations,
                operation_factory=self._operation_factory,
                actor=actor,
                operation=operation,
                credentials=prepared.credentials,
                plan=plan,
            )
        except ValueError as exc:
            self._fail_batch(
                actor=actor,
                operation=operation,
                prepared=prepared,
                error_code="zotero_import_invalid",
            )
            raise AppError(
                code="zotero_import_invalid",
                message="The selected Zotero items could not be imported",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from exc
        except Exception:
            self._fail_batch(
                actor=actor,
                operation=operation,
                prepared=prepared,
                error_code="zotero_import_failed",
            )
            raise

        complete_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        response = self._executor.command(
            lambda capabilities: capabilities.zotero.complete_import_batch(
                actor=actor,
                operation=complete_operation,
                prepared=prepared,
                result=result,
            )
        )
        if response.imported_count > 0:
            self._record_event(
                actor=actor,
                name="zotero_import_batch",
                properties={"count": response.imported_count},
            )
        return response

    def library(self, *, actor: Actor) -> ZoteroLibraryResponse:
        credentials = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_library(actor=actor)
        )
        snapshot = self._operations.fetch_library(credentials=credentials)
        return self._executor.query(
            lambda capabilities: capabilities.zotero.library(
                actor=actor,
                snapshot=snapshot,
            )
        )

    async def sync(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
    ) -> ZoteroSyncResponse:
        prepared = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_sync(actor=actor)
        )
        response = await _execute_sync(
            executor=self._executor,
            operations=self._operations,
            operation_factory=self._operation_factory,
            actor=actor,
            operation=operation,
            prepared=prepared,
        )
        if response.new_annotations_count > 0:
            self._record_event(
                actor=actor,
                name="zotero_manual_sync",
                properties={
                    "papers": response.synced_papers_count,
                    "annotations": response.new_annotations_count,
                },
            )
        return response

    def _fail_batch(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        prepared: PreparedZoteroImport,
        error_code: str,
    ) -> None:
        fail_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        self._executor.command(
            lambda capabilities: capabilities.zotero.fail_import_batch(
                actor=actor,
                operation=fail_operation,
                prepared=prepared,
                error_code=error_code,
            )
        )

    def _record_event(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object],
    ) -> None:
        try:
            self._operations.record_event(
                actor=actor,
                name=name,
                properties=properties,
            )
        except Exception:
            logger.warning("Zotero telemetry failed for %s", name, exc_info=True)


class ZoteroPostprocessWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        operations: ZoteroOperations,
        operation_factory: OperationContextFactory,
    ) -> None:
        self._executor = executor
        self._operations = operations
        self._operation_factory = operation_factory

    async def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        payload: dict[str, object],
    ) -> JobClaimResponse:
        try:
            callback = JobCallbackIdentity.model_validate(payload)
        except ValueError as exc:
            raise AppError(
                code="job_callback_invalid",
                message="Job callback payload is invalid for its operation",
                kind=FailureKind.UNPROCESSABLE,
            ) from exc
        prepared = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_postprocess(
                actor=actor,
                job_id=job_id,
                callback_task_id=callback.task_id,
            )
        )
        if prepared.disposition == "already_completed":
            return JobClaimResponse(claimed=False)
        stage_operation = self._operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        if prepared.disposition == "skip":
            assert prepared.skip_reason is not None
            result = ZoteroPostprocessResult(
                synced_papers_count=0,
                new_annotations_count=0,
                auto_imported_count=0,
                skipped_reason=prepared.skip_reason,
            )
        else:
            result = await self._run(
                actor=actor,
                operation=stage_operation,
                prepared=prepared,
            )
        complete_operation = self._operation_factory.child(
            stage_operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        changed = self._executor.command(
            lambda capabilities: capabilities.zotero.complete_postprocess(
                actor=actor,
                operation=complete_operation,
                prepared=prepared,
                result=result,
            )
        )
        if changed and actor is not None:
            self._record_event(actor=actor, result=result)
        return JobClaimResponse(claimed=changed)

    async def _run(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        prepared: PreparedZoteroPostprocess,
    ) -> ZoteroPostprocessResult:
        if actor is None or prepared.credentials is None:
            raise RuntimeError("runnable_zotero_postprocess_owner_missing")
        try:
            sync_prepared = self._executor.query(
                lambda capabilities: capabilities.zotero.prepare_sync(actor=actor)
            )
            sync_result = await _execute_sync(
                executor=self._executor,
                operations=self._operations,
                operation_factory=self._operation_factory,
                actor=actor,
                operation=operation,
                prepared=sync_prepared,
            )
            auto_imported = await self._auto_import(
                actor=actor,
                operation=operation,
                credentials=prepared.credentials,
            )
            return ZoteroPostprocessResult(
                synced_papers_count=sync_result.synced_papers_count,
                new_annotations_count=sync_result.new_annotations_count,
                auto_imported_count=auto_imported,
            )
        except Exception:
            fail_operation = self._operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            self._executor.command(
                lambda capabilities: capabilities.zotero.fail_postprocess(
                    actor=actor,
                    operation=fail_operation,
                    job_id=prepared.job_id,
                    error_code="zotero_postprocess_failed",
                )
            )
            raise

    async def _auto_import(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        credentials: ZoteroCredentials,
    ) -> int:
        import_since = self._executor.query(
            lambda capabilities: capabilities.zotero.auto_import_since(actor=actor)
        )
        if import_since is None:
            return 0
        library = self._operations.fetch_library(
            credentials=credentials,
            limit=100,
        )
        items = tuple(
            item
            for item in library.items
            if (
                (added := self._operations.parse_date_added(item.date_added))
                is not None
                and added >= import_since
            )
        )
        if not items:
            return 0
        plan = self._executor.query(
            lambda capabilities: capabilities.zotero.plan_import(
                actor=actor,
                items=items,
            )
        )
        result = await _execute_import_plan(
            executor=self._executor,
            operations=self._operations,
            operation_factory=self._operation_factory,
            actor=actor,
            operation=operation,
            credentials=credentials,
            plan=plan,
        )
        return result.imported_count

    def _record_event(
        self,
        *,
        actor: Actor,
        result: ZoteroPostprocessResult,
    ) -> None:
        try:
            self._operations.record_event(
                actor=actor,
                name="zotero_auto_sync",
                properties={
                    "papers": result.synced_papers_count,
                    "annotations": result.new_annotations_count,
                    "auto_imported": result.auto_imported_count,
                },
            )
        except Exception:
            logger.warning(
                "Zotero telemetry failed for zotero_auto_sync",
                exc_info=True,
            )


async def _execute_sync(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operations: ZoteroOperations,
    operation_factory: OperationContextFactory,
    actor: Actor,
    operation: OperationContext,
    prepared: PreparedZoteroSync,
) -> ZoteroSyncResponse:
    batch = await operations.fetch_sync_batch(
        credentials=prepared.credentials,
        targets=prepared.targets,
    )
    complete_operation = operation_factory.child(
        operation,
        initiated_by=OperationInitiator.SYSTEM,
    )
    return executor.command(
        lambda capabilities: capabilities.zotero.complete_sync(
            actor=actor,
            operation=complete_operation,
            batch=batch,
        )
    )


async def _execute_import_plan(
    *,
    executor: ApplicationExecutor[ApplicationCapabilities],
    operations: ZoteroOperations,
    operation_factory: OperationContextFactory,
    actor: Actor,
    operation: OperationContext,
    credentials: ZoteroCredentials,
    plan: ZoteroImportPlan,
) -> ZoteroImportResponse:
    imported = []
    errors = list(plan.errors)
    document_by_item_key: dict[str, UUID] = {}
    dimensions_by_item_key: dict[str, PageDimensions] = {}

    for planned in plan.items:
        if planned.disposition == "link_existing":
            existing_document_id = planned.document_id
            assert existing_document_id is not None
            attachment = await operations.fetch_attachment(
                credentials=credentials,
                item=planned.item,
            )
            dimensions = await operations.fetch_page_dimensions(
                source_key=planned.document_source_key,
            )
            link_operation = operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            executor.command(
                lambda capabilities: capabilities.zotero.link_import_item(
                    actor=actor,
                    operation=link_operation,
                    item=planned.item,
                    attachment=attachment,
                    document_id=existing_document_id,
                    page_dimensions=dimensions,
                )
            )
            continue
        if planned.disposition == "link_batch":
            continue

        content = await operations.fetch_import_content(
            credentials=credentials,
            item=planned.item,
        )
        if content.pdf_content is None:
            error_code = content.error or "No PDF available"
            failure_operation = operation_factory.child(
                operation,
                initiated_by=OperationInitiator.SYSTEM,
            )
            executor.command(
                lambda capabilities: capabilities.zotero.fail_import_item(
                    actor=actor,
                    operation=failure_operation,
                    item_key=planned.item.item_key,
                    upload_job_id=None,
                    error_code=error_code,
                )
            )
            errors.append(
                ZoteroImportError(
                    zotero_item_key=planned.item.item_key,
                    error=error_code,
                )
            )
            continue

        prepared_paper = PreparedPaperInput(
            content=content.pdf_content,
            filename=f"zotero-{planned.item.item_key}.pdf",
        )
        reserve_operation = operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        reservation: IngestionReservation | None = None
        ingestion: IngestPaper | None = None

        def reserve(capabilities: ApplicationCapabilities) -> IngestionReservation:
            reservation = capabilities.paper_ingestion.reserve(
                actor=actor,
                operation=reserve_operation,
                prepared=prepared_paper,
                project_id=None,
                idempotency_key=None,
            )
            capabilities.zotero.reserve_import_item(
                actor=actor,
                item_key=planned.item.item_key,
                upload_job_id=reservation.job_id,
            )
            return reservation

        try:
            reservation = executor.command(reserve)
            ingestion = executor.query(
                lambda capabilities: capabilities.paper_ingestion
            )
            await ingestion.acquire(actor=actor, job_id=reservation.job_id)
            await operations.upload_pdf(content=content.pdf_content)
            finalize_operation = operation_factory.child(
                reserve_operation,
                initiated_by=OperationInitiator.SYSTEM,
            )

            def finalize(
                capabilities: ApplicationCapabilities,
            ) -> tuple[IngestionFinalization, ZoteroImportItemResult]:
                finalization = capabilities.paper_ingestion.finalize(
                    actor=actor,
                    operation=finalize_operation,
                    job_id=reservation.job_id,
                    prepared=prepared_paper,
                )
                item_result = capabilities.zotero.complete_import_item(
                    actor=actor,
                    operation=finalize_operation,
                    item=planned.item,
                    attachment=content.attachment,
                    upload_job_id=reservation.job_id,
                    document_id=finalization.document_id,
                    reused_document=finalization.job_completed,
                    page_dimensions=content.page_dimensions,
                )
                return finalization, item_result

            finalization, item_result = executor.command(finalize)
            imported.append(item_result)
            document_by_item_key[planned.item.item_key] = finalization.document_id
            dimensions_by_item_key[planned.item.item_key] = content.page_dimensions
            if finalization.job_completed:
                await ingestion.release(actor=actor, job_id=reservation.job_id)
        except Exception:
            logger.exception(
                "Zotero item import failed",
                extra={"zotero_item_key": planned.item.item_key},
            )
            if reservation is not None and ingestion is not None:
                failure_operation = operation_factory.child(
                    reserve_operation,
                    initiated_by=OperationInitiator.SYSTEM,
                )

                def fail(capabilities: ApplicationCapabilities) -> None:
                    capabilities.paper_ingestion.fail(
                        actor=actor,
                        operation=failure_operation,
                        job_id=reservation.job_id,
                        error_code="zotero_import_failed",
                    )
                    capabilities.zotero.fail_import_item(
                        actor=actor,
                        operation=failure_operation,
                        item_key=planned.item.item_key,
                        upload_job_id=reservation.job_id,
                        error_code="zotero_import_failed",
                    )

                executor.command(fail)
                await ingestion.release(actor=actor, job_id=reservation.job_id)
            errors.append(
                ZoteroImportError(
                    zotero_item_key=planned.item.item_key,
                    error="zotero_import_failed",
                )
            )

    for planned in plan.items:
        if planned.disposition != "link_batch":
            continue
        source_item_key = planned.source_item_key
        assert source_item_key is not None
        document_id = document_by_item_key.get(source_item_key)
        if document_id is None:
            continue
        attachment = await operations.fetch_attachment(
            credentials=credentials,
            item=planned.item,
        )
        link_operation = operation_factory.child(
            operation,
            initiated_by=OperationInitiator.SYSTEM,
        )
        executor.command(
            lambda capabilities: capabilities.zotero.link_import_item(
                actor=actor,
                operation=link_operation,
                item=planned.item,
                attachment=attachment,
                document_id=document_id,
                page_dimensions=dimensions_by_item_key.get(
                    source_item_key,
                    (),
                ),
            )
        )

    return ZoteroImportResponse(
        imported=imported,
        imported_count=len(imported),
        imported_via_url=sum(item.import_source == "url" for item in imported),
        skipped_already_imported=plan.skipped_already_imported,
        errors=errors,
    )


__all__ = ["ZoteroOperations", "ZoteroPostprocessWorkflow", "ZoteroWorkflow"]
