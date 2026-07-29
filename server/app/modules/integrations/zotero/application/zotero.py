"""Zotero connection, import, and synchronization use cases."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroDisconnectResponse,
    ZoteroImportRequest,
    ZoteroImportResponse,
    ZoteroImportStatusListResponse,
    ZoteroLibraryResponse,
    ZoteroStatusResponse,
    ZoteroSyncResponse,
)
from app.modules.jobs.application.jobs import (
    IdempotentOperationPort,
    ReserveOperationCommand,
)
from app.shared.application import Actor
from app.shared.domain import AppError, JsonValue
from app.shared.domain.enums import JobOperation, JobStatus
from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ZoteroGateway(Protocol):
    def begin_oauth(self, *, user_id: int) -> str | None: ...

    def complete_oauth(self, *, oauth_token: str, oauth_verifier: str) -> bool: ...

    def status(self, *, user_id: int) -> ZoteroStatusResponse: ...

    def disconnect(self, *, user_id: int) -> bool: ...

    def connected(self, *, user_id: int) -> bool: ...

    def library(self, *, actor: Actor) -> ZoteroLibraryResponse: ...

    async def import_items(
        self,
        *,
        actor: Actor,
        request: ZoteroImportRequest,
    ) -> ZoteroImportResponse: ...

    async def sync(self, *, actor: Actor) -> ZoteroSyncResponse: ...

    def imports(
        self,
        *,
        user_id: int,
        item_keys: list[str] | None,
    ) -> ZoteroImportStatusListResponse: ...


class ZoteroImportCapacity(Protocol):
    def require(self, *, actor: Actor) -> None: ...


class ZoteroEvents(Protocol):
    def record(
        self,
        *,
        actor: Actor,
        name: str,
        properties: dict[str, object],
    ) -> None: ...


class Zotero:
    def __init__(
        self,
        *,
        gateway: ZoteroGateway,
        capacity: ZoteroImportCapacity,
        events: ZoteroEvents,
        idempotency: IdempotentOperationPort,
    ) -> None:
        self._gateway = gateway
        self._capacity = capacity
        self._events = events
        self._idempotency = idempotency

    def connect(self, *, actor: Actor) -> ZoteroConnectResponse:
        auth_url = self._gateway.begin_oauth(user_id=actor.id)
        if auth_url is None:
            raise AppError(
                code="zotero_connection_failed",
                message="Zotero authorization is temporarily unavailable",
                status_code=502,
            )
        return ZoteroConnectResponse(auth_url=auth_url)

    def callback(self, *, oauth_token: str, oauth_verifier: str) -> bool:
        return self._gateway.complete_oauth(
            oauth_token=oauth_token,
            oauth_verifier=oauth_verifier,
        )

    def status(self, *, actor: Actor) -> ZoteroStatusResponse:
        return self._gateway.status(user_id=actor.id)

    def disconnect(self, *, actor: Actor) -> ZoteroDisconnectResponse:
        deleted = self._gateway.disconnect(user_id=actor.id)
        return ZoteroDisconnectResponse(
            success=deleted,
            message=(
                "Zotero account disconnected"
                if deleted
                else "No Zotero account connected"
            ),
        )

    def library(self, *, actor: Actor) -> ZoteroLibraryResponse:
        self._require_connected(actor)
        return self._gateway.library(actor=actor)

    async def import_items(
        self,
        *,
        actor: Actor,
        request: ZoteroImportRequest,
        idempotency_key: str | None,
    ) -> ZoteroImportResponse:
        self._require_connected(actor)
        self._capacity.require(actor=actor)

        reservation_id = None
        if idempotency_key:
            reservation_id = uuid4()
            request_payload = _JSON_OBJECT.validate_python(
                {"item_keys": sorted(request.item_keys)}
            )
            reserved = self._idempotency.reserve(
                command=ReserveOperationCommand(
                    operation_id=reservation_id,
                    operation=JobOperation.ZOTERO_IMPORT,
                    requested_by_id=actor.id,
                    idempotency_key=(f"zotero-import:{actor.id}:{idempotency_key}"),
                    payload=request_payload,
                )
            )
            if reserved.payload != request_payload:
                raise AppError(
                    code="idempotency_key_reused",
                    message="The Idempotency-Key was already used for another request",
                    status_code=409,
                )
            if not reserved.created:
                if (
                    reserved.job.status == JobStatus.COMPLETED.value
                    and reserved.job.result is not None
                ):
                    return ZoteroImportResponse.model_validate(reserved.job.result)
                raise AppError(
                    code="idempotency_request_in_progress",
                    message="The original request is still in progress",
                    status_code=409,
                )

        try:
            result = await self._gateway.import_items(actor=actor, request=request)
        except ValueError as exc:
            raise AppError(
                code="zotero_import_invalid",
                message="The selected Zotero items could not be imported",
                status_code=400,
            ) from exc

        if result.imported_count > 0:
            self._events.record(
                actor=actor,
                name="zotero_import_batch",
                properties={"count": result.imported_count},
            )
        if reservation_id is not None:
            self._idempotency.complete(
                operation_id=reservation_id,
                result=_JSON_OBJECT.validate_python(result.model_dump(mode="json")),
            )
        return result

    async def sync(self, *, actor: Actor) -> ZoteroSyncResponse:
        self._require_connected(actor)
        result = await self._gateway.sync(actor=actor)
        if result.new_annotations_count > 0:
            self._events.record(
                actor=actor,
                name="zotero_manual_sync",
                properties={
                    "papers": result.synced_papers_count,
                    "annotations": result.new_annotations_count,
                },
            )
        return result

    def imports(
        self,
        *,
        actor: Actor,
        item_keys: list[str] | None,
    ) -> ZoteroImportStatusListResponse:
        return self._gateway.imports(user_id=actor.id, item_keys=item_keys)

    def _require_connected(self, actor: Actor) -> None:
        if not self._gateway.connected(user_id=actor.id):
            raise AppError(
                code="zotero_not_connected",
                message="Connect a Zotero account before using this feature",
                status_code=400,
            )
