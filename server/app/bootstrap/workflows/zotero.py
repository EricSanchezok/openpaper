"""Application/external/application orchestration for Zotero."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from app.bootstrap.capabilities import ApplicationCapabilities
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroLibraryResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroCallback,
    PreparedZoteroImport,
    ZoteroAccessToken,
    ZoteroCredentials,
    ZoteroRequestToken,
)
from app.shared.application import Actor, ApplicationExecutor
from app.shared.domain import AppError, FailureKind


class ZoteroOperations(Protocol):
    def request_token(self) -> ZoteroRequestToken | None: ...

    def authorize_url(self, *, request_token: ZoteroRequestToken) -> str: ...

    def exchange_access_token(
        self,
        *,
        callback: PreparedZoteroCallback,
        verifier: str,
    ) -> ZoteroAccessToken | None: ...

    def library(
        self,
        *,
        actor: Actor,
        credentials: ZoteroCredentials,
    ) -> ZoteroLibraryResponse: ...

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

    def connect(self, *, actor: Actor) -> ZoteroConnectResponse:
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
                request_token=request_token,
                auth_url=auth_url,
            )
        )

    def callback(self, *, oauth_token: str, oauth_verifier: str) -> bool:
        callback = self._executor.command(
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
        return self._executor.command(
            lambda capabilities: capabilities.zotero.complete_oauth_callback(
                callback=callback,
                access_token=access_token,
            )
        )

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

    def library(self, *, actor: Actor) -> ZoteroLibraryResponse:
        credentials = self._executor.query(
            lambda capabilities: capabilities.zotero.prepare_library(actor=actor)
        )
        return self._operations.library(
            actor=actor,
            credentials=credentials,
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
