import uuid
from datetime import datetime, timezone

from app.database.crud.base_crud import CRUDBase
from app.database.models import (
    Document,
    JobStatus,
    LibraryPaper,
    PaperUploadJob,
    ProjectPaper,
)
from app.policies.projects import get_project_access
from app.schemas.user import CurrentUser
from app.services.upload_lifecycle import active_upload_freshness_clause
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


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

        Dead jobs are filtered using the same freshness contract as the
        reservation reaper.
        """
        now = datetime.now(timezone.utc)
        statement = (
            select(PaperUploadJob, Document)
            .join(Document, Document.id == PaperUploadJob.document_id)
            .join(
                LibraryPaper,
                LibraryPaper.document_id == Document.id,
            )
            .where(
                PaperUploadJob.user_id == user.id,
                LibraryPaper.user_id == user.id,
                PaperUploadJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                active_upload_freshness_clause(now),
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

        The Document and its ProjectPaper association are created at upload
        start by ``services.document_submission``, so the job is reachable via
        PaperUploadJob.document_id points at the canonical Document. Returns jobs
        that have not yet completed so the client can rehydrate the upload
        tracker after a page refresh.
        """
        # Only the owner and collaborators may see in-progress Project uploads.
        if get_project_access(db, project_id=project_id, user_id=user.id) is None:
            return []

        now = datetime.now(timezone.utc)

        statement = (
            select(PaperUploadJob, Document)
            .join(Document, Document.id == PaperUploadJob.document_id)
            .join(ProjectPaper, ProjectPaper.document_id == Document.id)
            .where(
                ProjectPaper.project_id == project_id,
                PaperUploadJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                active_upload_freshness_clause(now),
            )
            .order_by(PaperUploadJob.created_at.asc())
        )
        return list(db.execute(statement).tuples().all())


# Create a single instance to use throughout the application
paper_upload_job_crud = PaperUploadJobCRUD(PaperUploadJob)
