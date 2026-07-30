"""Focused Zotero annotation and synchronization tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.bootstrap.adapters import zotero_gateway as gateway_module
from app.bootstrap.adapters.zotero_annotations import (
    _normalized_annotation,
    _page_number,
    apply_annotation_snapshot,
)
from app.bootstrap.adapters.zotero_gateway import DefaultZoteroGateway
from app.bootstrap.adapters.zotero_operations import _annotations_json
from app.modules.integrations.zotero.application.zotero import (
    ZoteroSyncBatch,
    ZoteroSyncTarget,
    ZoteroSyncUpdate,
)
from app.shared.application import Actor


def _actor() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
    )


def test_annotation_snapshot_serialization_keeps_stable_remote_keys() -> None:
    serialized = _annotations_json(
        [
            {"key": "ANN1", "data": {"annotationText": "hello"}},
            {"key": "", "data": {"annotationText": "skip"}},
        ]
    )
    assert json.loads(serialized) == [
        {"key": "ANN1", "data": {"annotationText": "hello"}}
    ]
    assert _normalized_annotation(json.loads(serialized)[0]) == (
        "ANN1",
        {"annotationText": "hello"},
    )
    assert _normalized_annotation({"annotationText": "legacy"}) is None


def test_page_number_prefers_pdf_page_index_over_printed_label() -> None:
    assert (
        _page_number(
            {
                "annotationPageLabel": "583",
                "annotationPosition": json.dumps(
                    {"pageIndex": 0, "rects": [[0, 0, 1, 1]]}
                ),
            }
        )
        == 1
    )


def test_apply_annotation_snapshot_is_idempotent_by_zotero_key() -> None:
    db = MagicMock()
    actor = _actor()
    document_id = uuid4()
    raw_file = SimpleNamespace(
        raw_content="hello world",
        page_offsets={1: (0, 11)},
    )
    annotation = {
        "key": "ANN1",
        "data": {
            "annotationType": "highlight",
            "annotationText": "hello",
            "annotationPosition": json.dumps(
                {"pageIndex": 0, "rects": [[0, 0, 10, 10]]}
            ),
        },
    }

    with (
        patch(
            "app.bootstrap.adapters.zotero_annotations.require_parsed_content",
            return_value=raw_file,
        ),
        patch.object(
            gateway_module,
            "apply_annotation_snapshot",
            wraps=apply_annotation_snapshot,
        ),
        patch(
            "app.bootstrap.adapters.zotero_annotations.research_repository"
        ) as repository,
    ):
        repository.get_zotero_annotation_keys.return_value = {"ANN1"}
        assert (
            apply_annotation_snapshot(
                db,
                document_id=document_id,
                user=actor,
                annotations_payload=[annotation],
                page_dimensions=((0, 612.0, 792.0),),
            )
            == 0
        )
        repository.create_highlight_thread.assert_not_called()


def test_apply_sync_with_empty_annotations_does_not_require_paper_content() -> None:
    db = MagicMock()
    actor = _actor()
    document_id = uuid4()
    imported_item_id = uuid4()
    imported_item = SimpleNamespace(
        id=imported_item_id,
        document_id=document_id,
    )
    target = ZoteroSyncTarget(
        imported_item_id=imported_item_id,
        item_key="ITEM",
        document_id=document_id,
        attachment_key="ATTACHMENT",
        document_source_key="documents/source.pdf",
    )
    batch = ZoteroSyncBatch(
        updates=(
            ZoteroSyncUpdate(
                target=target,
                annotations_json="[]",
                page_dimensions=(),
            ),
        ),
        failed_item_keys=(),
    )

    with (
        patch.object(
            gateway_module.zotero_import_repository,
            "get_by_item_key",
            return_value=imported_item,
        ),
        patch.object(
            gateway_module.zotero_import_repository,
            "update_after_sync",
        ),
        patch.object(
            gateway_module.document_repository,
            "find_accessible",
            return_value=SimpleNamespace(id=document_id),
        ),
        patch.object(gateway_module, "apply_annotation_snapshot") as apply,
    ):
        mutation = DefaultZoteroGateway(db).apply_sync(actor=actor, batch=batch)

    assert mutation.response.synced_papers_count == 1
    assert mutation.response.new_annotations_count == 0
    assert mutation.changed_document_ids == ()
    apply.assert_not_called()


def test_syncable_repository_excludes_url_imports() -> None:
    from app.modules.integrations.zotero.infrastructure.import_repository import (
        zotero_import_repository,
    )

    db = MagicMock()
    db.scalars.return_value.all.return_value = []

    zotero_import_repository.list_syncable_by_user(db, user_id=7, limit=10)

    statement = db.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "zotero_imported_items.import_source = 'pdf_attachment'" in compiled
    assert "zotero_imported_items.zotero_attachment_key IS NOT NULL" in compiled
