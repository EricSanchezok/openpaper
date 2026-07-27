from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.database.models import Document, Project
from app.errors import AppError
from app.services.project_lifecycle import (
    ProjectDeletionPlan,
    delete_orphan_documents,
    delete_project_storage,
    prepare_project_deletion,
)
from sqlalchemy.orm import Session


def _scalars_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = values
    return result


def test_project_deletion_detaches_private_chats_and_collects_owned_storage() -> None:
    project = Project(id=uuid4(), owner_id=1, title="Shared corpus")
    document = Document(
        id=uuid4(),
        file_url="s3://bucket/paper.pdf",
        s3_object_key="papers/paper.pdf",
        parser_markdown_s3_key="parses/paper.md",
        parser_archive_s3_key="parses/paper.zip",
    )
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [0, 0, 0]
    db.scalars.side_effect = [
        _scalars_result([document]),
        _scalars_result(["images/page-1.png"]),
        _scalars_result(["audio/project.mp3"]),
    ]

    plan = prepare_project_deletion(db, project=project)

    assert plan.orphan_documents == (document,)
    assert set(plan.storage_keys) == {
        "papers/paper.pdf",
        "parses/paper.md",
        "parses/paper.zip",
        "images/page-1.png",
        "audio/project.mp3",
    }
    # One bulk UPDATE detaches private conversations; one DELETE removes
    # Project-scoped artifacts.
    assert db.execute.call_count == 2

    delete_orphan_documents(db, plan=plan)
    db.delete.assert_called_once_with(document)


def test_project_deletion_is_blocked_while_any_project_job_is_active() -> None:
    db = MagicMock(spec=Session)
    db.scalar.side_effect = [1, 0, 0]

    with pytest.raises(AppError) as error:
        prepare_project_deletion(
            db,
            project=Project(id=uuid4(), owner_id=1, title="Busy"),
        )

    assert error.value.code == "project_has_active_jobs"
    db.scalars.assert_not_called()
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
        orphan_documents=(),
        storage_keys=("first", "second"),
    )

    # Post-commit cleanup must never turn a successful Project deletion into a
    # misleading 500 response.
    delete_project_storage(plan=plan)

    assert delete_file.call_count == 2
