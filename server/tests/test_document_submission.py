from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.database.models import Document, JobStatus, PaperUploadJob
from app.schemas.user import CurrentUser
from app.services.document_submission import submit_reserved_document
from sqlalchemy.orm import Session


def _user() -> CurrentUser:
    return CurrentUser(
        id=7,
        email="researcher@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def _upload_job(*, project_id=None) -> PaperUploadJob:
    return PaperUploadJob(
        id=uuid4(),
        user_id=7,
        quota_owner_id=11 if project_id else 7,
        project_id=project_id,
        reserved_size_kb=2,
        original_filename="source.pdf",
        status=JobStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_personal_submission_persists_identity_before_broker_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock(spec=Session)
    upload_job = _upload_job()
    document = Document(id=uuid4(), file_url="https://files/paper.pdf")
    upload_file = AsyncMock(return_value=("papers/paper.pdf", document.file_url))
    create_document = MagicMock(return_value=document)
    submit_job = MagicMock(return_value=str(upload_job.id))
    monkeypatch.setattr(
        "app.services.document_submission.s3_service.upload_file",
        upload_file,
    )
    monkeypatch.setattr(
        "app.services.document_submission.paper_crud.create",
        create_document,
    )
    monkeypatch.setattr(
        "app.services.document_submission.jobs_client.submit_pdf_processing_job",
        submit_job,
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
    assert upload_job.task_id == str(upload_job.id)
    create_document.assert_called_once()
    assert create_document.call_args.kwargs["add_to_library"] is True
    db.commit.assert_called_once()
    submit_job.assert_called_once_with("papers/paper.pdf", str(upload_job.id))


@pytest.mark.asyncio
async def test_project_submission_consumes_reserved_project_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    upload_job = _upload_job(project_id=project_id)
    document = Document(
        id=uuid4(),
        file_url="https://files/project.pdf",
        upload_job_id=upload_job.id,
    )
    db = MagicMock(spec=Session)
    attach = MagicMock()
    monkeypatch.setattr(
        "app.services.document_submission.s3_service.upload_file",
        AsyncMock(return_value=("papers/project.pdf", document.file_url)),
    )
    monkeypatch.setattr(
        "app.services.document_submission.paper_crud.create",
        MagicMock(return_value=document),
    )
    monkeypatch.setattr(
        "app.services.document_submission.project_paper_crud.attach_reserved_upload",
        attach,
    )
    monkeypatch.setattr(
        "app.services.document_submission.jobs_client.submit_pdf_processing_job",
        MagicMock(return_value=str(upload_job.id)),
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
        user=_user(),
        project_id=project_id,
        auto_commit=False,
    )
