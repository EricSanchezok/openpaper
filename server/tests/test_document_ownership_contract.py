"""Contracts for canonical documents and their user/project references."""

from pathlib import Path
import uuid
from unittest.mock import MagicMock

from app.database.models import Base, Document
from app.repositories.documents import document_repository
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import Session

ROOT = Path(__file__).parents[2]


def test_project_upload_can_create_a_document_without_personal_library_entry() -> None:
    db = MagicMock(spec=Session)
    document = Document(
        id=uuid.uuid4(),
        sha256="a" * 64,
        original_filename="document.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
    )
    db.scalar.return_value = document.id
    db.get.return_value = document

    result = document_repository.get_or_create(
        db,
        sha256=document.sha256,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        s3_object_key=document.s3_object_key,
        created_by_id=42,
        processing_job_id=uuid.uuid4(),
    )

    assert result.document is document
    assert result.created is True
    db.add.assert_not_called()


def test_personal_reference_attachment_is_conflict_safe() -> None:
    db = MagicMock(spec=Session)
    db.scalar.return_value = None

    result = document_repository.attach_library(
        db,
        document_id=uuid.uuid4(),
        user_id=42,
    )

    assert result.created is False
    statement = str(db.scalar.call_args.args[0])
    assert "ON CONFLICT" in statement


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
