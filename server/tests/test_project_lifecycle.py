from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.database.models import Document, Project
from app.errors import AppError
from app.services.project_lifecycle import (
    ProjectDeletionPlan,
    prepare_project_deletion,
    schedule_orphan_documents,
    schedule_project_storage_cleanup,
)
from sqlalchemy.orm import Session


def _scalars_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    return result


def test_project_deletion_preserves_private_chats_and_schedules_document_gc() -> None:
    project = Project(id=uuid4(), owner_id=1, title="Shared corpus")
    document = Document(
        id=uuid4(),
        sha256="a" * 64,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
    )
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [
        _scalars_result([]),
        _scalars_result([document.id]),
        _scalars_result(["audio/project.mp3"]),
    ]

    plan = prepare_project_deletion(db, project=project)

    assert plan.candidate_document_ids == (document.id,)
    assert set(plan.storage_keys) == {"audio/project.mp3"}
    # Private conversations survive and are marked read-only. Project-scoped
    # research items are removed by their database cascade.
    assert db.execute.call_count == 1

    schedule_gc = MagicMock()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "app.services.document_gc.schedule_document_gc",
        schedule_gc,
    )
    try:
        schedule_orphan_documents(db, plan=plan)
    finally:
        monkeypatch.undo()
    schedule_gc.assert_called_once_with(db, document_id=document.id)


def test_project_deletion_is_blocked_while_any_project_job_is_active() -> None:
    db = MagicMock(spec=Session)
    db.scalars.side_effect = [
        _scalars_result([uuid4()]),
    ]

    with pytest.raises(AppError) as error:
        prepare_project_deletion(
            db,
            project=Project(id=uuid4(), owner_id=1, title="Busy"),
        )

    assert error.value.code == "project_has_active_jobs"
    assert db.scalars.call_count == 1
    db.execute.assert_not_called()


def test_storage_cleanup_is_persisted_before_project_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_delete = MagicMock()
    monkeypatch.setattr(
        "app.services.storage_cleanup.schedule_storage_deletion",
        schedule_delete,
    )
    plan = ProjectDeletionPlan(
        candidate_document_ids=(),
        storage_keys=("first", "second"),
    )

    db = MagicMock(spec=Session)
    project_id = uuid4()
    schedule_project_storage_cleanup(db, project_id=project_id, plan=plan)

    schedule_delete.assert_called_once_with(
        db,
        object_keys=("first", "second"),
        idempotency_key=f"project:{project_id}",
    )
