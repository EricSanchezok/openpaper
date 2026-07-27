import uuid
from datetime import datetime, timedelta, timezone

from app.database.crud.base_crud import CRUDBase
from app.database.models import (
    Document,
    JobStatus,
    LibraryPaper,
    PaperUploadJob,
    ProjectPaper,
)
from app.schemas.user import CurrentUser
from app.policies.projects import get_project_access
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

# In-progress upload jobs older than this are treated as dead — a worker that
# died before writing a terminal status leaves a job stuck in PENDING/RUNNING
# forever (there is no reaper). A real PDF upload+parse finishes in minutes, so
# any in-progress job older than this window is filtered out of upload trackers.
# Single source of truth for the "stale upload" threshold.
STALE_UPLOAD_JOB_CUTOFF = timedelta(minutes=30)


# Define Pydantic models for type safety
class PaperUploadJobBase(BaseModel):
    status: JobStatus | None = JobStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    task_id: str | None = None
    quota_owner_id: int
    project_id: uuid.UUID | None = None
    reserved_size_kb: int = 0
    original_filename: str | None = None
    error_code: str | None = None


class PaperUploadJobCreate(PaperUploadJobBase):
    # user_id will be set based on current_user, so not required in input
    pass


class PaperUploadJobUpdate(BaseModel):
    quota_owner_id: int | None = None
    project_id: uuid.UUID | None = None
    status: JobStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    task_id: str | None = None
    reserved_size_kb: int | None = None
    original_filename: str | None = None
    error_code: str | None = None


# PaperUploadJob CRUD that inherits from the base CRUD
class PaperUploadJobCRUD(
    CRUDBase[PaperUploadJob, PaperUploadJobCreate, PaperUploadJobUpdate]
):
    """CRUD operations specifically for PaperUploadJob model"""

    def mark_as_running(
        self, db: Session, *, job_id: str, user: CurrentUser
    ) -> PaperUploadJob | None:
        """Mark a job as running and set started_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self.update(
                db=db,
                db_obj=job,
                obj_in=PaperUploadJobUpdate(
                    status=JobStatus.RUNNING, started_at=datetime.now(timezone.utc)
                ),
                user=user,
            )
        return None

    def mark_as_completed(
        self, db: Session, *, job_id: str, user: CurrentUser
    ) -> PaperUploadJob | None:
        """Mark a job as completed and set completed_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self.update(
                db=db,
                db_obj=job,
                obj_in=PaperUploadJobUpdate(
                    status=JobStatus.COMPLETED, completed_at=datetime.now(timezone.utc)
                ),
                user=user,
            )
        return None

    def mark_as_failed(
        self,
        db: Session,
        *,
        job_id: str,
        user: CurrentUser,
        error_code: str = "upload_failed",
    ) -> PaperUploadJob | None:
        """Mark a job as failed and set completed_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self.update(
                db=db,
                db_obj=job,
                obj_in=PaperUploadJobUpdate(
                    status=JobStatus.FAILED,
                    completed_at=datetime.now(timezone.utc),
                    error_code=error_code,
                ),
                user=user,
            )
        return None

    def mark_as_cancelled(
        self, db: Session, *, job_id: str, user: CurrentUser
    ) -> PaperUploadJob | None:
        """Mark a job as cancelled and set completed_at timestamp"""
        job = self.get(db, id=job_id, user=user)
        if job:
            return self.update(
                db=db,
                db_obj=job,
                obj_in=PaperUploadJobUpdate(
                    status=JobStatus.CANCELLED,
                    completed_at=datetime.now(timezone.utc),
                ),
                user=user,
            )
        return None

    def get_user_jobs(
        self, db: Session, *, user: CurrentUser, skip: int = 0, limit: int = 100
    ) -> list[PaperUploadJob]:
        """Get all paper upload jobs for a specific user"""
        return list(
            db.scalars(
                select(PaperUploadJob)
                .where(PaperUploadJob.user_id == user.id)
                .order_by(PaperUploadJob.created_at.desc())
                .offset(skip)
                .limit(limit)
            ).all()
        )

    def get_in_progress_jobs_for_user(
        self, db: Session, *, user: CurrentUser
    ) -> list[tuple[PaperUploadJob, Document]]:
        """
        Get in-progress jobs for documents in the user's personal library.

        Project-only uploads are deliberately excluded and are exposed through
        ``get_in_progress_jobs_for_project`` instead.

        Dead jobs (worker died before writing a terminal status) are filtered
        out via STALE_UPLOAD_JOB_CUTOFF so they don't resurface on every load.
        """
        stale_cutoff = datetime.now(timezone.utc) - STALE_UPLOAD_JOB_CUTOFF
        statement = (
            select(PaperUploadJob, Document)
            .join(Document, Document.upload_job_id == PaperUploadJob.id)
            .join(
                LibraryPaper,
                LibraryPaper.document_id == Document.id,
            )
            .where(
                PaperUploadJob.user_id == user.id,
                LibraryPaper.user_id == user.id,
                PaperUploadJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                PaperUploadJob.created_at >= stale_cutoff,
            )
            .order_by(PaperUploadJob.created_at.asc())
        )
        return list(db.execute(statement).tuples().all())

    def get_in_progress_jobs_for_project(
        self, db: Session, *, project_id: uuid.UUID, user: CurrentUser
    ) -> list[tuple[PaperUploadJob, Document]]:
        """
        Get upload jobs that are still in progress for a project, paired with
        their paper record.

        The paper and its ProjectPaper association are created at upload start
        (see helpers/pdf_jobs.py), so we can reach the job via
        ProjectPaper -> Document.upload_job_id -> PaperUploadJob. Returns jobs that
        have not yet completed so the client can rehydrate the upload tracker
        after a page refresh.
        """
        # Only members of the project may see its in-progress uploads.
        if get_project_access(db, project_id=project_id, user_id=user.id) is None:
            return []

        # Filter out dead uploads so a phantom job doesn't resurface every time
        # the project opens. See STALE_UPLOAD_JOB_CUTOFF.
        stale_cutoff = datetime.now(timezone.utc) - STALE_UPLOAD_JOB_CUTOFF

        statement = (
            select(PaperUploadJob, Document)
            .join(Document, Document.upload_job_id == PaperUploadJob.id)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(
                ProjectPaper.project_id == project_id,
                PaperUploadJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                PaperUploadJob.created_at >= stale_cutoff,
            )
            .order_by(PaperUploadJob.created_at.asc())
        )
        return list(db.execute(statement).tuples().all())


# Create a single instance to use throughout the application
paper_upload_job_crud = PaperUploadJobCRUD(PaperUploadJob)
