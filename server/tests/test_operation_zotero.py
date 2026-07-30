"""Focused OperationContext and journal behavior for the Zotero vertical."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest

from app.bootstrap.workflows.zotero import (
    ZoteroPostprocessWorkflow,
    ZoteroWorkflow,
)
from app.modules.integrations.zotero.application.contracts import (
    ZoteroConnectResponse,
    ZoteroSyncResponse,
)
from app.modules.integrations.zotero.application.zotero import (
    PreparedZoteroCallback,
    PreparedZoteroPostprocess,
    PreparedZoteroSync,
    Zotero,
    ZoteroAccessToken,
    ZoteroConnectionChange,
    ZoteroRequestToken,
    ZoteroSyncBatch,
    ZoteroSyncMutation,
)
from app.modules.operation_journal.application import OperationJournal
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    JobOrigin,
    OAuthCallbackOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    SchedulerOrigin,
)
from app.modules.jobs.application.callbacks import (
    JobCallbacks,
    ScheduledZoteroJobs,
)
from app.shared.domain import AppError


def _actor(actor_id: int = 7) -> Actor:
    return Actor(
        id=actor_id,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _service(
    *,
    gateway: MagicMock,
    journal: MagicMock,
    idempotency: MagicMock | None = None,
) -> Zotero:
    return Zotero(
        gateway=gateway,
        capacity=MagicMock(),
        idempotency=idempotency or MagicMock(),
        journal=journal,
    )


def test_oauth_pending_persists_only_causality_and_is_not_journaled() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    service = _service(gateway=gateway, journal=journal)
    operation = _operation()
    token = ZoteroRequestToken(token="request-token", secret="secret")

    response = service.save_oauth_request(
        actor=_actor(),
        operation=operation,
        request_token=token,
        auth_url="https://www.zotero.org/oauth/authorize",
    )

    assert response == ZoteroConnectResponse(
        auth_url="https://www.zotero.org/oauth/authorize"
    )
    assert gateway.save_oauth_request.call_args.kwargs == {
        "user_id": 7,
        "request_token": token,
        "correlation_id": operation.trace.correlation_id,
        "origin_operation_id": operation.trace.operation_id,
    }
    journal.append.assert_not_called()


def test_expired_oauth_callback_is_read_only() -> None:
    gateway = MagicMock()
    gateway.oauth_callback.return_value = PreparedZoteroCallback(
        user_id=7,
        request_token=ZoteroRequestToken(token="expired", secret="secret"),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        correlation_id=uuid4(),
        origin_operation_id=uuid4(),
    )
    service = _service(
        gateway=gateway,
        journal=MagicMock(spec=OperationJournal),
    )

    assert (
        service.prepare_oauth_callback(
            oauth_token="expired",
            now=datetime.now(UTC),
        )
        is None
    )
    assert gateway.method_calls == [
        call.oauth_callback(oauth_token="expired"),
    ]


def test_connection_change_journals_once_and_rejects_owner_mismatch() -> None:
    gateway = MagicMock()
    connection_id = uuid4()
    gateway.save_connection.return_value = ZoteroConnectionChange(
        connection_id=connection_id,
        changed=True,
    )
    journal = MagicMock(spec=OperationJournal)
    service = _service(gateway=gateway, journal=journal)
    operation = _operation()
    callback = PreparedZoteroCallback(
        user_id=7,
        request_token=ZoteroRequestToken(token="token", secret="secret"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id=operation.trace.correlation_id,
        origin_operation_id=operation.trace.operation_id,
    )
    access_token = ZoteroAccessToken(user_id="remote-user", api_key="api-key")

    assert service.complete_oauth_callback(
        actor=_actor(),
        operation=operation,
        callback=callback,
        access_token=access_token,
    )
    assert journal.append.call_args.kwargs["action"] == ("zotero.connection_connected")

    gateway.save_connection.return_value = ZoteroConnectionChange(
        connection_id=connection_id,
        changed=False,
    )
    journal.reset_mock()
    assert service.complete_oauth_callback(
        actor=_actor(),
        operation=operation,
        callback=callback,
        access_token=access_token,
    )
    journal.append.assert_not_called()

    with pytest.raises(AppError) as raised:
        service.complete_oauth_callback(
            actor=_actor(8),
            operation=operation,
            callback=callback,
            access_token=access_token,
        )
    assert raised.value.code == "zotero_callback_owner_mismatch"


def test_disconnect_and_sync_suppress_noop_journal_entries() -> None:
    gateway = MagicMock()
    journal = MagicMock(spec=OperationJournal)
    service = _service(gateway=gateway, journal=journal)
    actor = _actor()
    operation = _operation()

    gateway.disconnect.return_value = None
    service.disconnect(actor=actor, operation=operation)
    journal.append.assert_not_called()

    gateway.disconnect.return_value = uuid4()
    service.disconnect(actor=actor, operation=operation)
    assert journal.append.call_args.kwargs["action"] == (
        "zotero.connection_disconnected"
    )

    journal.reset_mock()
    gateway.apply_sync.return_value = ZoteroSyncMutation(
        response=ZoteroSyncResponse(
            synced_papers_count=1,
            new_annotations_count=0,
        ),
        changed_document_ids=(),
    )
    service.complete_sync(
        actor=actor,
        operation=operation,
        batch=ZoteroSyncBatch(updates=(), failed_item_keys=()),
    )
    journal.append.assert_not_called()

    changed_document_id = uuid4()
    gateway.apply_sync.return_value = ZoteroSyncMutation(
        response=ZoteroSyncResponse(
            synced_papers_count=1,
            new_annotations_count=2,
        ),
        changed_document_ids=(changed_document_id,),
    )
    service.complete_sync(
        actor=actor,
        operation=operation,
        batch=ZoteroSyncBatch(updates=(), failed_item_keys=()),
    )
    assert journal.append.call_args.kwargs["action"] == "zotero.annotations_synced"
    assert journal.append.call_args.kwargs["resources"][0].id == str(
        changed_document_id
    )


class _Executor:
    def __init__(self, capabilities: object) -> None:
        self._capabilities = capabilities

    def query(self, operation):  # type: ignore[no-untyped-def]
        return operation(self._capabilities)

    def command(self, operation):  # type: ignore[no-untyped-def]
        return operation(self._capabilities)


def test_oauth_workflow_resumes_verified_owner_causality() -> None:
    actor = _actor()
    correlation_id = uuid4()
    origin_operation_id = uuid4()
    callback = PreparedZoteroCallback(
        user_id=actor.id,
        request_token=ZoteroRequestToken(token="token", secret="secret"),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        correlation_id=correlation_id,
        origin_operation_id=origin_operation_id,
    )
    zotero = MagicMock()
    zotero.prepare_oauth_callback.return_value = callback
    zotero.complete_oauth_callback.return_value = True
    identity = MagicMock()
    identity.resolve_actor_by_user_id.return_value = actor
    operations = MagicMock()
    operations.exchange_access_token.return_value = ZoteroAccessToken(
        user_id="remote-user",
        api_key="api-key",
    )
    workflow = ZoteroWorkflow(
        executor=_Executor(  # type: ignore[arg-type]
            SimpleNamespace(zotero=zotero, identity=identity)
        ),
        operations=operations,
        operation_factory=OperationContextFactory(),
    )
    request = RequestReference(uuid4())

    assert workflow.callback(
        oauth_token="token",
        oauth_verifier="verifier",
        request=request,
    )

    operation = zotero.complete_oauth_callback.call_args.kwargs["operation"]
    assert operation.trace.correlation_id == correlation_id
    assert operation.trace.causation_id == origin_operation_id
    assert operation.initiated_by is OperationInitiator.SYSTEM
    assert operation.credential is None
    assert operation.origin == OAuthCallbackOrigin(
        request=request,
        provider="zotero",
    )
    assert zotero.complete_oauth_callback.call_args.kwargs["actor"] is actor


@pytest.mark.asyncio
async def test_postprocess_uses_prepare_external_finalize_short_stages() -> None:
    actor = _actor()
    job_id = uuid4()
    credentials = MagicMock()
    prepared = PreparedZoteroPostprocess(
        job_id=job_id,
        credentials=credentials,
        disposition="run",
    )
    events: list[str] = []
    zotero = MagicMock()
    zotero.prepare_postprocess.side_effect = lambda **_kwargs: (
        events.append("prepare") or prepared
    )
    zotero.prepare_sync.side_effect = lambda **_kwargs: (
        events.append("prepare_sync")
        or PreparedZoteroSync(credentials=credentials, targets=())
    )
    zotero.complete_sync.side_effect = lambda **_kwargs: (
        events.append("complete_sync")
        or ZoteroSyncResponse(
            synced_papers_count=2,
            new_annotations_count=3,
        )
    )
    zotero.auto_import_since.side_effect = lambda **_kwargs: (
        events.append("auto_import_window") or None
    )
    zotero.complete_postprocess.side_effect = lambda **_kwargs: (
        events.append("finalize") or True
    )
    operations = MagicMock()

    async def fetch_sync_batch(**_kwargs):  # type: ignore[no-untyped-def]
        events.append("external_sync")
        return ZoteroSyncBatch(updates=(), failed_item_keys=())

    operations.fetch_sync_batch = AsyncMock(side_effect=fetch_sync_batch)
    workflow = ZoteroPostprocessWorkflow(
        executor=_Executor(SimpleNamespace(zotero=zotero)),  # type: ignore[arg-type]
        operations=operations,
        operation_factory=OperationContextFactory(),
    )
    operation = OperationContextFactory().resume(
        correlation_id=uuid4(),
        causation_id=uuid4(),
        initiated_by=OperationInitiator.SYSTEM,
        origin=JobOrigin(job_id=job_id, delivery_ref=None, request_id=uuid4()),
        credential=None,
    )

    response = await workflow.complete(
        actor=actor,
        operation=operation,
        job_id=job_id,
        payload={"task_id": str(job_id)},
    )

    assert response.claimed is True
    assert events == [
        "prepare",
        "prepare_sync",
        "external_sync",
        "complete_sync",
        "auto_import_window",
        "finalize",
    ]
    sync_operation = zotero.complete_sync.call_args.kwargs["operation"]
    complete_operation = zotero.complete_postprocess.call_args.kwargs["operation"]
    assert sync_operation.trace.causation_id == complete_operation.trace.causation_id
    assert sync_operation.trace.causation_id != operation.trace.operation_id
    assert complete_operation.trace.correlation_id == operation.trace.correlation_id


@pytest.mark.asyncio
async def test_postprocess_failure_uses_child_operation_and_failure_stage() -> None:
    actor = _actor()
    job_id = uuid4()
    prepared = PreparedZoteroPostprocess(
        job_id=job_id,
        credentials=MagicMock(),
        disposition="run",
    )
    events: list[str] = []
    zotero = MagicMock()
    zotero.prepare_postprocess.side_effect = lambda **_kwargs: (
        events.append("prepare") or prepared
    )
    zotero.prepare_sync.return_value = PreparedZoteroSync(
        credentials=prepared.credentials,
        targets=(),
    )
    zotero.fail_postprocess.side_effect = lambda **_kwargs: (
        events.append("fail") or True
    )
    operations = MagicMock()

    async def fail_external_sync(**_kwargs):  # type: ignore[no-untyped-def]
        events.append("external")
        raise RuntimeError("provider unavailable")

    operations.fetch_sync_batch = AsyncMock(side_effect=fail_external_sync)
    workflow = ZoteroPostprocessWorkflow(
        executor=_Executor(SimpleNamespace(zotero=zotero)),  # type: ignore[arg-type]
        operations=operations,
        operation_factory=OperationContextFactory(),
    )
    operation = OperationContextFactory().resume(
        correlation_id=uuid4(),
        causation_id=uuid4(),
        initiated_by=OperationInitiator.SYSTEM,
        origin=JobOrigin(job_id=job_id, delivery_ref=None, request_id=uuid4()),
        credential=None,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await workflow.complete(
            actor=actor,
            operation=operation,
            job_id=job_id,
            payload={"task_id": str(job_id)},
        )

    assert events == ["prepare", "external", "fail"]
    zotero.complete_postprocess.assert_not_called()
    fail_operation = zotero.fail_postprocess.call_args.kwargs["operation"]
    assert fail_operation.trace.causation_id != operation.trace.operation_id
    assert fail_operation.trace.correlation_id == operation.trace.correlation_id


def test_scheduler_journals_only_jobs_that_were_created() -> None:
    created_job_id = uuid4()
    schedules = MagicMock()
    schedules.schedule_zotero_sync.return_value = ScheduledZoteroJobs(
        total_users=2,
        scheduled_jobs=1,
        skipped_users=1,
        created_job_ids=(created_job_id,),
    )
    journal = MagicMock(spec=OperationJournal)
    callbacks = JobCallbacks(
        lifecycle=MagicMock(),
        handlers={},
        schedules=schedules,
        journal=journal,
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin(task_name="zotero_sync", run_id=uuid4()),
        credential=None,
    )

    response = callbacks.schedule_zotero_sync(
        operation=operation,
        threshold_seconds=3600,
    )

    assert response["scheduled_jobs"] == 1
    assert schedules.schedule_zotero_sync.call_args.kwargs == {
        "threshold_seconds": 3600,
        "correlation_id": operation.trace.correlation_id,
        "origin_operation_id": operation.trace.operation_id,
    }
    change = tuple(journal.append_many.call_args.kwargs["changes"])[0]
    assert change.action == "job.created"
    assert change.resources[0].id == str(created_job_id)
