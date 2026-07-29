"""Application/external/application orchestration for Zotero."""

from __future__ import annotations

from typing import Protocol

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroImport,
    ZoteroCredentials,
)
from app.shared.application import Actor, ApplicationExecutor
from app.shared.domain import AppError, FailureKind


class ZoteroOperations(Protocol):
    async def import_items(
        self,
        *,
        actor: Actor,
        prepared: PreparedZoteroImport,
    ) -> ZoteroImportResponse: ...

    async def sync(
        self,
        *,
        actor: Actor,
        credentials: ZoteroCredentials,
    ) -> ZoteroSyncResponse: ...


class ZoteroWorkflow:
    def __init__(
        self,
        *,
        executor: ApplicationExecutor[ApplicationCapabilities],
        operations: ZoteroOperations,
    ) -> None:
        self._executor = executor
        self._operations = operations

    async def import_items(
        self,
        *,
        actor: Actor,
        request: ZoteroImportRequest,
        idempotency_key: str | None,
    ) -> ZoteroImportResponse:
        prepared = self._executor.command(
            lambda capabilities: capabilities.zotero.prepare_import(
                actor=actor,
                request=request,
                idempotency_key=idempotency_key,
            )
        )
        if isinstance(prepared, ZoteroImportResponse):
            return prepared

        try:
            result = await self._operations.import_items(
                actor=actor,
                prepared=prepared,
            )
        except ValueError as exc:
            self._fail(prepared=prepared, error_code="zotero_import_invalid")
            raise AppError(
                code="zotero_import_invalid",
                message="The selected Zotero items could not be imported",
                kind=FailureKind.INVALID_ARGUMENT,
            ) from exc
        except Exception:
            self._fail(prepared=prepared, error_code="zotero_import_failed")
            raise

        return self._executor.command(
            lambda capabilities: capabilities.zotero.complete_import(
                actor=actor,
                prepared=prepared,
                result=result,
            )
        )

    async def sync(self, *, actor: Actor) -> ZoteroSyncResponse:
        credentials = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_sync(actor=actor)
        )
        result = await self._operations.sync(
            actor=actor,
            credentials=credentials,
        )
        return self._executor.command(
            lambda capabilities: capabilities.zotero.complete_sync(
                actor=actor,
                result=result,
            )
        )

    def _fail(
        self,
        *,
        prepared: PreparedZoteroImport,
        error_code: str,
    ) -> None:
        self._executor.command(
            lambda capabilities: capabilities.zotero.fail_import(
                prepared=prepared,
                error_code=error_code,
            )
        )
