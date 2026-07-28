"""Contracts for canonical documents and their user/project references."""

from pathlib import Path
from unittest.mock import MagicMock
import uuid

from app.database.crud.paper_crud import PaperCreate, paper_crud
from app.database.models import Base, Document, LibraryPaper
from app.schemas.user import CurrentUser
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[2]


def _user() -> CurrentUser:
    return CurrentUser(
        id=42,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _session() -> MagicMock:
    db = MagicMock(spec=Session)

    def assign_document_id(instance: object) -> None:
        if isinstance(instance, Document) and instance.id is None:
            instance.id = uuid.uuid4()

    db.add.side_effect = assign_document_id
    return db


def test_project_upload_can_create_a_document_without_personal_library_entry() -> None:
    db = _session()

    document = paper_crud.create(
        db,
        obj_in=PaperCreate(
            sha256="a" * 64,
            original_filename="document.pdf",
            size_bytes=1024,
            s3_object_key=f"documents/{'a' * 64}/source.pdf",
        ),
        user=_user(),
        add_to_library=False,
        auto_commit=False,
    )

    assert isinstance(document, Document)
    added = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(item, Document) for item in added)
    assert not any(isinstance(item, LibraryPaper) for item in added)


def test_personal_upload_creates_exactly_one_library_entry() -> None:
    db = _session()

    document = paper_crud.create(
        db,
        obj_in=PaperCreate(
            sha256="a" * 64,
            original_filename="document.pdf",
            size_bytes=1024,
            s3_object_key=f"documents/{'a' * 64}/source.pdf",
        ),
        user=_user(),
        auto_commit=False,
    )

    assert isinstance(document, Document)
    added = [call.args[0] for call in db.add.call_args_list]
    entries = [item for item in added if isinstance(item, LibraryPaper)]
    assert len(entries) == 1
    assert entries[0].document_id == document.id
    assert entries[0].user_id == 42


def test_metadata_and_baseline_expose_only_canonical_ownership_tables() -> None:
    tables = set(Base.metadata.tables)
    assert {
        "scholens.documents",
        "scholens.library_papers",
        "scholens.project_papers",
        "scholens.library_paper_tags",
    } <= tables
    assert "scholens.papers" not in tables
    assert "scholens.paper_tag_association" not in tables

    library_table = Base.metadata.tables["scholens.library_papers"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in library_table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("user_id", "document_id") in unique_columns

    baseline = next((ROOT / "server" / "migrations" / "versions").glob("*.py"))
    source = baseline.read_text(encoding="utf-8")
    assert '"documents"' in source
    assert '"library_papers"' in source
    assert '"project_papers"' in source
    assert '"papers"' not in source
