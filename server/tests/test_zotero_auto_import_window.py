"""Zotero automatic-import window behavior on the unified workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.bootstrap.adapters.zotero_operations import DefaultZoteroOperations
from app.bootstrap.workflows.zotero import ZoteroPostprocessWorkflow
from app.modules.integrations.zotero.application.zotero import (
    ZoteroCredentials,
    ZoteroImportPlan,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
)
from app.shared.application import Actor, OperationContextFactory


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _item(key: str, date_added: str) -> ZoteroItemSnapshot:
    return ZoteroItemSnapshot(
        item_key=key,
        title=key,
        authors=(),
        abstract=None,
        publish_date=None,
        doi=None,
        tags=(),
        date_added=date_added,
        item_type="journalArticle",
        venue=None,
        collections=(),
        has_pdf_attachment=True,
        has_metadata=True,
    )


class _Executor:
    def __init__(self, capabilities: object) -> None:
        self.capabilities = capabilities

    def query(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.capabilities)

    def command(self, operation):  # type: ignore[no-untyped-def]
        return operation(self.capabilities)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-06-01T10:15:30Z", datetime(2024, 6, 1, 10, 15, 30, tzinfo=UTC)),
        ("not-a-date", None),
        (None, None),
    ],
)
def test_parse_date_added(value: str | None, expected: datetime | None) -> None:
    assert DefaultZoteroOperations.parse_date_added(value) == expected


@pytest.mark.asyncio
async def test_auto_import_only_plans_items_at_or_after_cutoff() -> None:
    since = datetime(2025, 6, 1, tzinfo=UTC)
    zotero = MagicMock()
    zotero.auto_import_since.return_value = since
    captured: list[tuple[str, ...]] = []

    def plan_import(*, items, **_kwargs):  # type: ignore[no-untyped-def]
        captured.append(tuple(item.item_key for item in items))
        return ZoteroImportPlan(items=(), skipped_already_imported=0, errors=())

    zotero.plan_import.side_effect = plan_import
    operations = MagicMock(spec=DefaultZoteroOperations)
    operations.fetch_library.return_value = ZoteroLibrarySnapshot(
        items=(
            _item("OLD", "2020-01-01T00:00:00Z"),
            _item("NEW", "2025-07-01T00:00:00Z"),
            _item("INVALID", "not-a-date"),
        )
    )
    operations.parse_date_added.side_effect = DefaultZoteroOperations.parse_date_added
    workflow = ZoteroPostprocessWorkflow(
        executor=_Executor(SimpleNamespace(zotero=zotero)),  # type: ignore[arg-type]
        operations=operations,
        operation_factory=OperationContextFactory(),
    )

    count = await workflow._auto_import(
        actor=_actor(),
        operation=MagicMock(),
        credentials=ZoteroCredentials(user_id="remote", api_key="secret"),
    )

    assert count == 0
    assert captured == [("NEW",)]


@pytest.mark.asyncio
async def test_auto_import_without_prior_completed_import_avoids_remote_io() -> None:
    zotero = MagicMock()
    zotero.auto_import_since.return_value = None
    operations = MagicMock(spec=DefaultZoteroOperations)
    workflow = ZoteroPostprocessWorkflow(
        executor=_Executor(SimpleNamespace(zotero=zotero)),  # type: ignore[arg-type]
        operations=operations,
        operation_factory=OperationContextFactory(),
    )

    count = await workflow._auto_import(
        actor=_actor(),
        operation=MagicMock(),
        credentials=ZoteroCredentials(user_id="remote", api_key="secret"),
    )

    assert count == 0
    operations.fetch_library.assert_not_called()
