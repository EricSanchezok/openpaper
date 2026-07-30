from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import (
    OperationAction,
    OperationChange,
    OperationJournalEntry,
    ResourceRef,
)
from app.modules.operation_journal.infrastructure import (
    SqlAlchemyOperationJournalStore,
)
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    JobOrigin,
    McpOrigin,
    OAuthCallbackOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
    SchedulerOrigin,
    WebhookOrigin,
)

NOW = datetime(2026, 7, 30, 22, tzinfo=timezone.utc)
DIGEST = "b" * 64


class _Clock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return NOW


class _Store:
    def __init__(self) -> None:
        self.batches: list[tuple[OperationJournalEntry, ...]] = []

    def append(self, entries: tuple[OperationJournalEntry, ...]) -> None:
        self.batches.append(entries)


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _journal() -> tuple[OperationJournal, _Store, _Clock]:
    store = _Store()
    clock = _Clock()
    generated = iter((uuid4(), uuid4(), uuid4()))
    return (
        OperationJournal(
            store=store,
            clock=clock,
            generate_uuid=lambda: next(generated),
        ),
        store,
        clock,
    )


def _root(
    *,
    operation_id: UUID,
    origin: object,
    initiated_by: OperationInitiator,
    credential: CredentialRef | None,
) -> OperationContext:
    return OperationContextFactory(lambda: operation_id).root(
        initiated_by=initiated_by,
        origin=origin,  # type: ignore[arg-type]
        credential=credential,
    )


def test_entry_normalizes_resources_and_batch_reads_clock_once() -> None:
    operation_id = uuid4()
    journal, store, clock = _journal()
    conversation_origin = ConversationOrigin(
        RequestReference(uuid4()),
        uuid4(),
        uuid4(),
    )
    operation = _root(
        operation_id=operation_id,
        origin=conversation_origin,
        initiated_by=OperationInitiator.USER,
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )

    entries = journal.append_many(
        actor=_actor(),
        operation=operation,
        changes=(
            OperationChange(
                action=OperationAction("project.updated"),
                resources=(
                    ResourceRef("project", "b"),
                    ResourceRef("project", "a"),
                    ResourceRef("project", "a"),
                ),
            ),
            OperationChange(
                action=OperationAction("project.paper_added"),
                resources=(ResourceRef("project", "b"),),
            ),
        ),
    )

    assert clock.calls == 1
    assert store.batches == [entries]
    assert [resource.id for resource in entries[0].resources] == ["a", "b"]
    assert all(entry.created_at == entry.updated_at == NOW for entry in entries)
    assert entries[0].actor_id == 7
    assert entries[0].conversation_id == conversation_origin.conversation_id
    assert entries[0].turn_id == conversation_origin.turn_id


@pytest.mark.parametrize(
    ("origin", "initiated_by", "credential", "expected"),
    [
        (
            McpOrigin(RequestReference(uuid4()), None, DIGEST),
            OperationInitiator.AGENT,
            CredentialRef(CredentialKind.ACCESS_KEY, str(uuid4())),
            ("stateless", DIGEST, None),
        ),
        (
            JobOrigin(uuid4(), DIGEST, uuid4()),
            OperationInitiator.SYSTEM,
            CredentialRef(CredentialKind.INTERNAL_SIGNATURE),
            ("job", DIGEST, "job"),
        ),
        (
            WebhookOrigin(RequestReference(uuid4()), "stripe", DIGEST),
            OperationInitiator.SYSTEM,
            CredentialRef(CredentialKind.PROVIDER_SIGNATURE),
            ("stripe", DIGEST, None),
        ),
        (
            OAuthCallbackOrigin(RequestReference(uuid4()), "zotero"),
            OperationInitiator.SYSTEM,
            None,
            ("zotero", None, None),
        ),
        (
            SchedulerOrigin("document_gc", uuid4()),
            OperationInitiator.SYSTEM,
            None,
            ("document_gc", "run", None),
        ),
    ],
)
def test_typed_origins_have_fixed_safe_projection(
    origin: object,
    initiated_by: OperationInitiator,
    credential: CredentialRef | None,
    expected: tuple[str, str | None, str | None],
) -> None:
    operation_id = uuid4()
    journal, _, _ = _journal()
    operation = _root(
        operation_id=operation_id,
        origin=origin,
        initiated_by=initiated_by,
        credential=credential,
    )

    entry = journal.append(
        actor=None,
        operation=operation,
        action=OperationAction("system.completed"),
        resources=(ResourceRef("operation", str(operation_id)),),
    )

    assert entry.origin_name == expected[0]
    if expected[1] == "run":
        assert entry.origin_reference == str(operation.origin.run_id)  # type: ignore[union-attr]
    else:
        assert entry.origin_reference == expected[1]
    if expected[2] == "job":
        assert entry.job_id == operation.origin.job_id  # type: ignore[union-attr]
    else:
        assert entry.job_id is None


def test_empty_batch_is_a_noop_without_time_or_store_write() -> None:
    operation_id = uuid4()
    journal, store, clock = _journal()
    operation = _root(
        operation_id=operation_id,
        origin=SchedulerOrigin("document_gc", uuid4()),
        initiated_by=OperationInitiator.SYSTEM,
        credential=None,
    )

    assert journal.append_many(actor=None, operation=operation, changes=()) == ()
    assert store.batches == []
    assert clock.calls == 0


@pytest.mark.parametrize(
    "action",
    ["Project.updated", "project", "project.", "project.updated-again"],
)
def test_action_requires_stable_lower_snake_pair(action: str) -> None:
    with pytest.raises(ValueError):
        OperationAction(action)


def test_change_requires_an_explicit_typed_action() -> None:
    with pytest.raises(TypeError, match="OperationAction"):
        OperationChange(  # type: ignore[arg-type]
            "project.updated",
            (ResourceRef("project", str(uuid4())),),
        )


def test_resource_invariants_reject_empty_and_more_than_one_hundred() -> None:
    with pytest.raises(ValueError, match="at least one"):
        OperationChange(OperationAction("project.updated"), ())

    with pytest.raises(ValueError, match="at most 100"):
        OperationChange(
            OperationAction("project.updated"),
            tuple(ResourceRef("paper", str(index)) for index in range(101)),
        )


def test_sqlalchemy_store_only_adds_and_flushes_current_session() -> None:
    operation_id = uuid4()
    journal, captured, _ = _journal()
    operation = _root(
        operation_id=operation_id,
        origin=SchedulerOrigin("document_gc", uuid4()),
        initiated_by=OperationInitiator.SYSTEM,
        credential=None,
    )
    entry = journal.append(
        actor=None,
        operation=operation,
        action=OperationAction("document.deleted"),
        resources=(ResourceRef("document", str(uuid4())),),
    )
    assert captured.batches == [(entry,)]

    session = MagicMock()
    SqlAlchemyOperationJournalStore(session).append((entry,))

    session.add_all.assert_called_once()
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()
    model = session.add_all.call_args.args[0][0]
    assert model.resources == [
        {"type": entry.resources[0].type, "id": entry.resources[0].id}
    ]
