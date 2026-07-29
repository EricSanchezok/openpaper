"""Zotero connection, import, and synchronization use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
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
from app.modules.integrations.zotero.domain import (
    ImportReservationAction,
    ImportReservationFacts,
    canonical_import_payload,
    decide_import_reservation,
    import_idempotency_key,
    require_zotero_connected,
)
from app.shared.application import Actor
from app.shared.domain import AppError, JsonValue, FailureKind
from app.shared.domain.enums import JobOperation, JobStatus
from pydantic import TypeAdapter

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class ZoteroGateway(Protocol):
    def begin_oauth(self, *, user_id: int) -> str | None: ...

    def complete_oauth(self, *, oauth_token: str, oauth_verifier: str) -> bool: ...

    def status(self, *, user_id: int) -> ZoteroStatusResponse: ...

    def disconnect(self, *, user_id: int) -> bool: ...

    def connected(self, *, user_id: int) -> bool: ...

    def credentials(self, *, user_id: int) -> ZoteroCredentials | None: ...

    def library(self, *, actor: Actor) -> ZoteroLibraryResponse: ...

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


@dataclass(frozen=True, slots=True)
class ZoteroCredentials:
    user_id: str
    api_key: str


@dataclass(frozen=True, slots=True)
class PreparedZoteroImport:
    credentials: ZoteroCredentials
    request: ZoteroImportRequest
    reservation_id: UUID | None


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
                kind=FailureKind.DEPENDENCY_FAILURE,
            )
        return ZoteroConnectResponse(auth_url=auth_url)

    def callback(self, *, oauth_token: str, oauth_verifier: str) -> bool:
        return self._gateway.complete_oauth(
            oauth_token=oauth_token,
            oauth_verifier=oauth_verifier,
        )

    def status(self, *, actor: Actor) -> ZoteroStatusResponse:
        return self._gateway.status(user_id=actor.id)

    def disconnect(self, *, actor: Actor) -> None:
        self._gateway.disconnect(user_id=actor.id)

    def library(self, *, actor: Actor) -> ZoteroLibraryResponse:
        self._require_connected(actor)
        return self._gateway.library(actor=actor)

    def prepare_import(
        self,
        *,
        actor: Actor,
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

        return PreparedZoteroImport(
            credentials=credentials,
            request=request,
            reservation_id=reservation_id,
        )

    def complete_import(
        self,
        *,
        actor: Actor,
        prepared: PreparedZoteroImport,
        result: ZoteroImportResponse,
    ) -> ZoteroImportResponse:
        if result.imported_count > 0:
            self._events.record(
                actor=actor,
                name="zotero_import_batch",
                properties={"count": result.imported_count},
            )
        if prepared.reservation_id is not None:
            self._idempotency.complete(
                operation_id=prepared.reservation_id,
                result=_JSON_OBJECT.validate_python(result.model_dump(mode="json")),
            )
        return result

    def fail_import(
        self,
        *,
        prepared: PreparedZoteroImport,
        error_code: str,
    ) -> None:
        if prepared.reservation_id is not None:
            self._idempotency.fail(
                operation_id=prepared.reservation_id,
                error_code=error_code,
            )

    def prepare_sync(self, *, actor: Actor) -> ZoteroCredentials:
        return self._require_credentials(actor)

    def complete_sync(
        self,
        *,
        actor: Actor,
        result: ZoteroSyncResponse,
    ) -> ZoteroSyncResponse:
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
        require_zotero_connected(
            connected=self._gateway.connected(user_id=actor.id),
        )

    def _require_credentials(self, actor: Actor) -> ZoteroCredentials:
        credentials = self._gateway.credentials(user_id=actor.id)
        require_zotero_connected(connected=credentials is not None)
        assert credentials is not None
        return credentials
