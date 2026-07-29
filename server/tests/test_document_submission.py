from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.database.models import (
    Document,
    DocumentProcessingStatus,
    DurableJob,
    JobOperation,
    JobStatus,
    UploadReservation,
)
from app.shared.application import Actor
from app.services.document_submission import submit_reserved_document
from sqlalchemy.orm import Session


def _user() -> Actor:
    return Actor(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _upload_job(*, project_id=None) -> UploadReservation:
    job_id = uuid4()
    durable_job = DurableJob(
        id=job_id,
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=7,
        project_id=project_id,
        idempotency_key=f"pdf-reservation:{job_id}",
        status=JobStatus.PENDING.value,
        payload={},
    )
    reservation = UploadReservation(
        id=job_id,
        quota_owner_id=11 if project_id else 7,
        reserved_size_kb=2,
        reserved_reference_count=1,
        original_filename="source.pdf",
    )
    reservation.job = durable_job
    return reservation


def _document(*, processing_job_id=None) -> Document:
    digest = "a" * 64
    return Document(
        id=uuid4(),
        sha256=digest,
        original_filename="source.pdf",
        mime_type="application/pdf",
        size_bytes=8,
        s3_object_key=f"documents/{digest}/source.pdf",
        processing_status=DocumentProcessingStatus.PENDING.value,
        processing_job_id=processing_job_id,
    )


@pytest.mark.asyncio
async def test_personal_submission_persists_identity_before_broker_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    upload_job = _upload_job()
    document = _document(processing_job_id=upload_job.id)
    upload_source = MagicMock()
    get_by_sha = MagicMock(return_value=None)
    get_or_create = MagicMock(
        return_value=SimpleNamespace(document=document, created=True)
    )
    attach_library = MagicMock(return_value=SimpleNamespace(created=True))
    add_dispatch = MagicMock()
    monkeypatch.setattr(
        "app.services.document_submission.s3_service.upload_document_source",
        upload_source,
    )
    monkeypatch.setattr(
        "app.services.document_submission.document_repository.get_by_sha256",
        get_by_sha,
    )
    monkeypatch.setattr(
        "app.services.document_submission.document_repository.get_or_create",
        get_or_create,
    )
    monkeypatch.setattr(
        "app.services.document_submission.document_repository.attach_library",
        attach_library,
    )
    monkeypatch.setattr(
        "app.services.document_submission.job_repository.add_dispatch",
        add_dispatch,
    )
    monkeypatch.setattr(
        "app.services.document_submission.track_event",
        MagicMock(),
    )

    task_id = await submit_reserved_document(
        pdf_bytes=b"%PDF-1.7",
        upload_job=upload_job,
        db=db,
        user=_user(),
    )

    assert task_id == str(upload_job.id)
    assert upload_job.job.document_id == document.id
    get_or_create.assert_called_once()
    attach_library.assert_called_once_with(
        db,
        document_id=document.id,
        user_id=7,
    )
    upload_source.assert_called_once()
    assert db.commit.call_count == 1
    assert add_dispatch.call_args.kwargs["job"] is upload_job.job
    assert add_dispatch.call_args.kwargs["task_name"] == "upload_and_process_file"
    task_kwargs = add_dispatch.call_args.kwargs["kwargs"]
    assert task_kwargs["s3_object_key"] == document.s3_object_key
    assert task_kwargs["claim_url"].endswith(f"/jobs/{upload_job.id}/claim")


@pytest.mark.asyncio
async def test_project_submission_consumes_reserved_project_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    upload_job = _upload_job(project_id=project_id)
    document = _document(processing_job_id=upload_job.id)
    db = MagicMock(spec=Session)
    attach = MagicMock(return_value=(SimpleNamespace(document_id=document.id), True))
    monkeypatch.setattr(
        "app.services.document_submission.s3_service.upload_document_source",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.document_submission.document_repository.get_by_sha256",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.services.document_submission.document_repository.get_or_create",
        MagicMock(return_value=SimpleNamespace(document=document, created=True)),
    )
    monkeypatch.setattr(
        "app.services.document_submission.project_document_repository.attach_reserved_upload",
        attach,
    )
    monkeypatch.setattr(
        "app.services.document_submission.job_repository.add_dispatch",
        MagicMock(),
    )
    monkeypatch.setattr(
        "app.services.document_submission.track_event",
        MagicMock(),
    )

    await submit_reserved_document(
        pdf_bytes=b"%PDF-1.7",
        upload_job=upload_job,
        db=db,
        user=_user(),
    )

    attach.assert_called_once_with(
        db=db,
        document=document,
            upload_job=upload_job,
            user=_user(),
            project_id=project_id,
        )
