"""S3, database, and broker hand-off for one reserved PDF upload."""

from __future__ import annotations

import logging
import time
from io import BytesIO

from app.database.crud.paper_crud import PaperCreate, paper_crud
from app.database.crud.projects.project_paper_crud import project_paper_crud
from app.database.models import Document, LibraryPaper, PaperUploadJob, ProjectPaper
from app.database.telemetry import track_event
from app.helpers.s3 import s3_service
from app.integrations.jobs_client import jobs_client
from app.schemas.user import CurrentUser
from sqlalchemy import delete
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _remove_failed_placeholder(
    db: Session,
    *,
    document: Document,
) -> None:
    db.execute(delete(LibraryPaper).where(LibraryPaper.document_id == document.id))
    db.execute(delete(ProjectPaper).where(ProjectPaper.document_id == document.id))
    db.flush()
    db.delete(document)
    db.commit()


async def submit_reserved_document(
    *,
    pdf_bytes: bytes,
    upload_job: PaperUploadJob,
    db: Session,
    user: CurrentUser,
) -> str:
    """Persist a placeholder and publish its deterministic Jobs task."""
    if not pdf_bytes:
        raise ValueError("pdf_bytes cannot be empty")

    job_id = str(upload_job.id)
    filename = f"{job_id}.pdf"
    logger.info(
        "Submitting reserved PDF: size=%s filename=%s job_id=%s",
        len(pdf_bytes),
        filename,
        job_id,
    )

    s3_object_key: str | None = None
    document: Document | None = None
    placeholder_committed = False
    try:
        upload_started_at = time.monotonic()
        s3_object_key, file_url = await s3_service.upload_file(
            BytesIO(pdf_bytes),
            filename,
        )
        track_event(
            "timer:initial_pdf_upload_for_microservice",
            user_id=str(user.id),
            properties={
                "duration": time.monotonic() - upload_started_at,
                "job_id": job_id,
            },
            sync=True,
            db=db,
        )

        document = paper_crud.create(
            db=db,
            obj_in=PaperCreate(
                file_url=file_url,
                s3_object_key=s3_object_key,
                upload_job_id=job_id,
                title=upload_job.original_filename,
                size_in_kb=upload_job.reserved_size_kb,
            ),
            user=user,
            add_to_library=upload_job.project_id is None,
            auto_commit=False,
        )
        if document is None:
            raise RuntimeError("document_placeholder_creation_failed")

        if upload_job.project_id is not None:
            project_paper_crud.attach_reserved_upload(
                db=db,
                document=document,
                user=user,
                project_id=upload_job.project_id,
                auto_commit=False,
            )

        # Persist both the placeholder and deterministic broker identity before
        # publish. A process crash leaves a recoverable row, never an unknown
        # Celery task ID.
        upload_job.task_id = job_id
        db.commit()
        placeholder_committed = True

        return jobs_client.submit_pdf_processing_job(s3_object_key, job_id)
    except Exception as exc:
        logger.exception("Reserved PDF submission failed for %s", job_id)
        db.rollback()
        if placeholder_committed and document is not None:
            try:
                _remove_failed_placeholder(db, document=document)
            except Exception:
                db.rollback()
                logger.exception(
                    "Failed to remove placeholder document %s",
                    document.id,
                )
        if s3_object_key:
            try:
                if not s3_service.delete_file(s3_object_key):
                    logger.error(
                        "Failed to remove S3 object after submission failure: %s",
                        s3_object_key,
                    )
            except Exception:
                logger.exception(
                    "Failed to remove S3 object after submission failure: %s",
                    s3_object_key,
                )
        raise RuntimeError("pdf_upload_submission_failed") from exc
