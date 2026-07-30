"""Focused Zotero import planning and short-transaction workflow tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters import zotero_gateway as gateway_module
from app.bootstrap.adapters.zotero_gateway import DefaultZoteroGateway
from app.bootstrap.workflows.zotero import _execute_import_plan
from app.database.models import ZoteroImportSource
from app.helpers.paper_search import normalize_doi
from app.modules.integrations.zotero.application.contracts import (
    ZoteroImportItemResult,
)
from app.modules.integrations.zotero.application.zotero import (
    ZoteroAttachmentSnapshot,
    ZoteroCredentials,
    ZoteroImportContent,
    ZoteroImportPlan,
    ZoteroImportPlanItem,
    ZoteroItemSnapshot,
)
from app.modules.papers.application.ingestion import (
    IngestionFinalization,
    IngestionReservation,
)
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)


def _actor() -> Actor:
    return Actor(
        id=42,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def _item(key: str, *, doi: str | None = None) -> ZoteroItemSnapshot:
    return ZoteroItemSnapshot(
        item_key=key,
        title=f"Paper {key}",
        authors=("Researcher",),
        abstract=None,
        publish_date="2026-01-01",
        doi=doi,
        tags=(),
        date_added="2026-01-02T00:00:00Z",
        item_type="journalArticle",
        venue=None,
        collections=(),
        has_pdf_attachment=True,
        has_metadata=True,
    )


def _operation():
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.1234/abc", "10.1234/abc"),
        ("https://doi.org/10.1234/abc", "10.1234/abc"),
        ("doi:10.1234/abc", "10.1234/abc"),
        (None, None),
        ("  ", None),
    ],
)
def test_normalize_doi(value: str | None, expected: str | None) -> None:
    assert normalize_doi(value) == expected


def test_plan_import_links_existing_and_duplicate_doi_without_title_dedup() -> None:
    existing_document = SimpleNamespace(
        id=uuid4(),
        s3_object_key="documents/existing.pdf",
    )
    gateway = DefaultZoteroGateway(MagicMock())
    items = (
        _item("EXISTING", doi="10.1000/existing"),
        _item("FIRST", doi="10.1000/new"),
        _item("SECOND", doi="https://doi.org/10.1000/new"),
        _item("NO-DOI"),
        _item("NO-DOI-2"),
    )

    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            return_value=None,
        ),
        patch.object(
            gateway_module.document_repository,
            "find_library_document_by_doi",
            side_effect=lambda _db, *, doi, **_kwargs: (
                existing_document if doi == "10.1000/existing" else None
            ),
        ),
        patch.object(
            gateway_module, "can_user_upload_paper", return_value=(True, None)
        ),
        patch.object(
            gateway_module,
            "get_remaining_paper_upload_slots",
            return_value=10,
        ),
    ):
        plan = gateway.plan_import(actor=_actor(), items=items)

    assert [planned.disposition for planned in plan.items] == [
        "link_existing",
        "import",
        "link_batch",
        "import",
        "import",
    ]
    assert plan.items[0].document_id == existing_document.id
    assert plan.items[2].source_item_key == "FIRST"
    assert plan.skipped_already_imported == 2
    assert plan.errors == ()


def test_plan_import_applies_remaining_capacity_only_to_new_documents() -> None:
    gateway = DefaultZoteroGateway(MagicMock())
    items = (_item("A"), _item("B"))

    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            return_value=None,
        ),
        patch.object(
            gateway_module.document_repository,
            "find_library_document_by_doi",
            return_value=None,
        ),
        patch.object(
            gateway_module, "can_user_upload_paper", return_value=(True, None)
        ),
        patch.object(
            gateway_module,
            "get_remaining_paper_upload_slots",
            return_value=1,
        ),
    ):
        plan = gateway.plan_import(actor=_actor(), items=items)

    assert [planned.item.item_key for planned in plan.items] == ["A"]
    assert [error.zotero_item_key for error in plan.errors] == ["B"]


class _StageExecutor:
    def __init__(self, capabilities: object, events: list[str]) -> None:
        self.capabilities = capabilities
        self.events = events
        self.inside_transaction = False

    def query(self, operation):  # type: ignore[no-untyped-def]
        assert not self.inside_transaction
        self.events.append("query")
        return operation(self.capabilities)

    def command(self, operation):  # type: ignore[no-untyped-def]
        assert not self.inside_transaction
        self.events.append("command:start")
        self.inside_transaction = True
        try:
            return operation(self.capabilities)
        finally:
            self.inside_transaction = False
            self.events.append("command:end")


@pytest.mark.asyncio
async def test_import_plan_keeps_remote_io_outside_commands() -> None:
    events: list[str] = []
    actor = _actor()
    item = _item("ITEM")
    attachment = ZoteroAttachmentSnapshot(
        item_key=item.item_key,
        import_source=ZoteroImportSource.PDF_ATTACHMENT,
        attachment_key="ATTACHMENT",
        source_url=None,
        annotations_json="[]",
    )
    content = ZoteroImportContent(
        item=item,
        attachment=attachment,
        pdf_content=b"%PDF-1.4",
        page_dimensions=((0, 612.0, 792.0),),
        error=None,
    )
    job_id = uuid4()
    document_id = uuid4()
    paper_ingestion = MagicMock()
    paper_ingestion.reserve.side_effect = lambda **_kwargs: (
        events.append("reserve_paper")
        or IngestionReservation(job_id=job_id, replayed=False)
    )
    paper_ingestion.acquire = AsyncMock(
        side_effect=lambda **_kwargs: events.append("acquire")
    )
    paper_ingestion.finalize.side_effect = lambda **_kwargs: (
        events.append("finalize_paper")
        or IngestionFinalization(
            task_id=str(job_id),
            job_id=job_id,
            document_id=document_id,
            project_id=None,
            changed=True,
            job_completed=False,
        )
    )
    zotero = MagicMock()
    zotero.reserve_import_item.side_effect = lambda **_kwargs: events.append(
        "reserve_zotero"
    )
    zotero.complete_import_item.side_effect = lambda **_kwargs: (
        events.append("complete_zotero")
        or ZoteroImportItemResult(
            zotero_item_key=item.item_key,
            document_id=str(document_id),
            upload_job_id=str(job_id),
            import_source=ZoteroImportSource.PDF_ATTACHMENT,
            title=item.title,
        )
    )
    capabilities = SimpleNamespace(
        paper_ingestion=paper_ingestion,
        zotero=zotero,
    )
    executor = _StageExecutor(capabilities, events)
    operations = MagicMock()

    async def fetch_import_content(**_kwargs):  # type: ignore[no-untyped-def]
        assert not executor.inside_transaction
        events.append("fetch_remote")
        return content

    async def upload_pdf(**_kwargs):  # type: ignore[no-untyped-def]
        assert not executor.inside_transaction
        events.append("upload_external")

    operations.fetch_import_content = AsyncMock(side_effect=fetch_import_content)
    operations.upload_pdf = AsyncMock(side_effect=upload_pdf)
    result = await _execute_import_plan(
        executor=executor,  # type: ignore[arg-type]
        operations=operations,
        operation_factory=OperationContextFactory(),
        actor=actor,
        operation=_operation(),
        credentials=ZoteroCredentials(user_id="remote", api_key="secret"),
        plan=ZoteroImportPlan(
            items=(ZoteroImportPlanItem(item=item, disposition="import"),),
            skipped_already_imported=0,
            errors=(),
        ),
    )

    assert result.imported_count == 1
    assert events == [
        "fetch_remote",
        "command:start",
        "reserve_paper",
        "reserve_zotero",
        "command:end",
        "query",
        "acquire",
        "upload_external",
        "command:start",
        "finalize_paper",
        "complete_zotero",
        "command:end",
    ]
