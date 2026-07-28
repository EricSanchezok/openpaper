from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.database.models import Document, Project
from app.errors import AppError
from app.services.project_lifecycle import (
    ProjectDeletionPlan,
    delete_project_storage,
    prepare_project_deletion,
    schedule_orphan_documents,
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
        _scalars_result([]),
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
        _scalars_result([]),
        _scalars_result([]),
    ]

    with pytest.raises(AppError) as error:
        prepare_project_deletion(
            db,
            project=Project(id=uuid4(), owner_id=1, title="Busy"),
        )

    assert error.value.code == "project_has_active_jobs"
    assert db.scalars.call_count == 3
    db.execute.assert_not_called()


def test_storage_cleanup_is_best_effort_after_database_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_file = MagicMock(side_effect=[True, RuntimeError("S3 unavailable")])
    monkeypatch.setattr(
        "app.services.project_lifecycle.s3_service.delete_file",
        delete_file,
    )
    plan = ProjectDeletionPlan(
        candidate_document_ids=(),
        storage_keys=("first", "second"),
    )

    # Post-commit cleanup must never turn a successful Project deletion into a
    # misleading 500 response.
    delete_project_storage(plan=plan)

    assert delete_file.call_count == 2
