from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from unittest.mock import MagicMock
from uuid import uuid4

from app.api.documents.router import (
    _library_response,
    list_library_papers,
)
from app.database.models import Document, LibraryPaper, PaperStatus
from app.main import app
from app.helpers.s3 import s3_service
from app.repositories.documents import document_repository
from app.schemas.user import CurrentUser
from app.schemas.tags import LibraryTagAssignmentRequest
from pydantic import ValidationError
import pytest
from sqlalchemy.orm import Session


def _current_user() -> CurrentUser:
    return CurrentUser(
        id=1,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _entry() -> LibraryPaper:
    now = datetime.now(timezone.utc)
    document = Document(
        id=uuid4(),
        sha256="a" * 64,
        original_filename="paper.pdf",
        mime_type="application/pdf",
        size_bytes=1024,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
        preview_s3_key=f"documents/{'a' * 64}/preview.webp",
        title="Canonical title",
        processing_status="completed",
        created_at=now,
        updated_at=now,
    )
    entry = LibraryPaper(
        id=uuid4(),
        user_id=1,
        document_id=document.id,
        status=PaperStatus.reading.value,
        last_accessed_at=now,
        metadata_overrides={"title": "My title"},
        is_public=False,
        created_at=now,
        updated_at=now,
    )
    entry.document = document
    entry.tags = []
    return entry


def test_library_list_uses_empty_collection_for_new_user(monkeypatch) -> None:
    monkeypatch.setattr(
        document_repository, "list_library", lambda *_args, **_kwargs: []
    )

    response = list_library_papers(
        db=MagicMock(spec=Session),
        current_user=_current_user(),
    )

    assert response.items == []


def test_library_response_returns_private_signed_preview(monkeypatch) -> None:
    entry = _entry()
    monkeypatch.setattr(
        s3_service,
        "generate_presigned_url",
        lambda *_args, **_kwargs: "https://signed.example.invalid/preview",
    )

    response = _library_response(entry)

    assert response.id == entry.id
    assert response.document.id == entry.document_id
    assert response.preview_url == "https://signed.example.invalid/preview"
    assert response.metadata_overrides.title == "My title"


def test_share_token_is_rotated_and_only_its_hash_is_persisted() -> None:
    entry = _entry()
    db = MagicMock(spec=Session)
    db.scalar.return_value = entry

    first = document_repository.rotate_public_share(
        db,
        library_paper_id=entry.id,
        user_id=entry.user_id,
    )
    first_hash = entry.share_token_hash
    second = document_repository.rotate_public_share(
        db,
        library_paper_id=entry.id,
        user_id=entry.user_id,
    )

    assert first != second
    assert first_hash == hashlib.sha256(first.encode()).hexdigest()
    assert entry.share_token_hash == hashlib.sha256(second.encode()).hexdigest()
    assert second not in entry.share_token_hash
    assert entry.is_public is True


def test_revoking_share_removes_the_only_public_credential() -> None:
    entry = _entry()
    entry.is_public = True
    entry.share_token_hash = hashlib.sha256(b"token").hexdigest()
    db = MagicMock(spec=Session)
    db.scalar.return_value = entry

    document_repository.revoke_public_share(
        db,
        library_paper_id=entry.id,
        user_id=entry.user_id,
    )

    assert entry.is_public is False
    assert entry.share_token_hash is None


def test_library_tag_api_uses_library_document_boundaries() -> None:
    paths = app.openapi()["paths"]

    assert "/api/documents/uploads" in paths
    assert "/api/documents/uploads/from-url" in paths
    assert "/api/library/tags" in paths
    assert "/api/library/tags/assignments" in paths
    assert "/api/library/papers/by-document/{document_id}/tags/{tag_id}" in paths
    assert not any(path.startswith("/api/paper/tag") for path in paths)
    assert not any(path.startswith("/api/paper/upload") for path in paths)


def test_library_tag_assignment_is_strict_and_bounded() -> None:
    document_id = uuid4()
    tag_id = uuid4()
    request = LibraryTagAssignmentRequest(
        document_ids=[document_id],
        tag_ids=[tag_id],
    )
    assert request.document_ids == [document_id]

    with pytest.raises(ValidationError):
        LibraryTagAssignmentRequest.model_validate(
            {
                "document_ids": [str(document_id), str(document_id)],
                "tag_ids": [str(tag_id)],
            }
        )
    with pytest.raises(ValidationError):
        LibraryTagAssignmentRequest.model_validate(
            {
                "document_ids": [str(document_id)],
                "tag_ids": [str(tag_id)],
                "legacy": True,
            }
        )
