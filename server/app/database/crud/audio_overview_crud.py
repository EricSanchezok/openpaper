from datetime import datetime, timezone
from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.models import (
    AudioOverview,
    AudioOverviewJob,
    ConversableType,
    JobStatus,
    Project,
    ProjectRole,
)
from app.schemas.responses import ResponseCitation
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class AudioOverviewJobBase(BaseModel):
    conversable_id: UUID
    conversable_type: ConversableType = ConversableType.PAPER


class AudioOverviewJobCreate(AudioOverviewJobBase):
    pass


class AudioOverviewJobUpdate(BaseModel):
    status: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AudioOverviewBase(BaseModel):
    conversable_id: UUID
    conversable_type: ConversableType = ConversableType.PAPER
    s3_object_key: str
    transcript: str | None = None
    citations: list[ResponseCitation] | None = None
    title: str | None = None


class AudioOverviewCreate(AudioOverviewBase):
    pass


class AudioOverviewUpdate(BaseModel):
    s3_object_key: str | None = None
    transcript: str | None = None
    citations: list[ResponseCitation] | None = None
    title: str | None = None


class AudioOverviewJobCRUD(
    CRUDBase[AudioOverviewJob, AudioOverviewJobCreate, AudioOverviewJobUpdate]
):
    """CRUD operations for AudioOverviewJob model"""

    def create(
        self,
        db: Session,
        *,
        obj_in: AudioOverviewJobCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> AudioOverviewJob | None:
        """Create a new audio overview job"""
        if user is None:
            raise ValueError("User must be provided to create an audio overview job")
        obj_in_data = obj_in.model_dump(exclude_unset=True)
        db_obj = AudioOverviewJob(**obj_in_data, user_id=user.id)

        db.add(db_obj)
        if auto_commit:
            db.commit()
            db.refresh(db_obj)
        else:
            db.flush()
        return db_obj

    def get_by_conversable_and_user(
        self,
        db: Session,
        *,
        conversable_id: UUID,
        conversable_type: ConversableType,
        current_user: CurrentUser,
    ) -> list[AudioOverviewJob] | None:
        """Get audio overviews by conversable ID, type and user"""
        if conversable_type == ConversableType.PAPER:
            # For papers, check direct ownership
            return list(
                db.scalars(
                    select(AudioOverviewJob)
                    .where(
                        AudioOverviewJob.conversable_id == conversable_id,
                        AudioOverviewJob.conversable_type == conversable_type,
                        AudioOverviewJob.user_id == current_user.id,
                    )
                    .order_by(AudioOverviewJob.created_at.desc())
                ).all()
            )
        elif conversable_type == ConversableType.PROJECT:
            # For projects, check user has project access through ProjectRole
            return list(
                db.scalars(
                    select(AudioOverviewJob)
                    .join(Project, AudioOverviewJob.conversable_id == Project.id)
                    .join(ProjectRole, Project.id == ProjectRole.project_id)
                    .where(
                        AudioOverviewJob.conversable_id == conversable_id,
                        AudioOverviewJob.conversable_type == conversable_type,
                        ProjectRole.user_id == current_user.id,
                    )
                    .order_by(AudioOverviewJob.created_at.desc())
                ).all()
            )

        # Fallback to direct ownership for other types
        return list(
            db.scalars(
                select(AudioOverviewJob)
                .where(
                    AudioOverviewJob.conversable_id == conversable_id,
                    AudioOverviewJob.conversable_type == conversable_type,
                    AudioOverviewJob.user_id == current_user.id,
                )
                .order_by(AudioOverviewJob.created_at.desc())
            ).all()
        )

    def get_user_jobs(
        self,
        db: Session,
        *,
        current_user: CurrentUser,
        status: str | None = None,
        conversable_type: ConversableType | None = None,
    ) -> list[AudioOverviewJob]:
        """Get all audio overview jobs for a user, optionally filtered by status and type"""
        statement = select(AudioOverviewJob).where(
            AudioOverviewJob.user_id == current_user.id
        )

        if status:
            statement = statement.where(AudioOverviewJob.status == status)

        if conversable_type:
            statement = statement.where(
                AudioOverviewJob.conversable_type == conversable_type
            )

        return list(
            db.scalars(statement.order_by(AudioOverviewJob.created_at.desc())).all()
        )

    def update_status(
        self,
        db: Session,
        *,
        job_id: UUID,
        status: str,
        current_user: CurrentUser,
        status_message: str | None = None,
    ) -> AudioOverviewJob | None:
        """Update job status with timestamp tracking"""
        job = db.scalars(
            select(AudioOverviewJob).where(
                AudioOverviewJob.id == job_id,
                AudioOverviewJob.user_id == current_user.id,
            )
        ).first()

        if not job:
            return None

        job.status = status

        if status_message is not None:
            job.status_message = status_message

        # Set timestamps based on status
        if status == JobStatus.RUNNING and not job.started_at:
            job.started_at = datetime.now(timezone.utc)
        elif status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            if not job.completed_at:
                job.completed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(job)
        return job

    def update_status_message(
        self,
        db: Session,
        *,
        job_id: UUID,
        status_message: str,
        current_user: CurrentUser,
    ) -> AudioOverviewJob | None:
        """Update only the status message without changing status"""
        job = db.scalars(
            select(AudioOverviewJob).where(
                AudioOverviewJob.id == job_id,
                AudioOverviewJob.user_id == current_user.id,
            )
        ).first()

        if not job:
            return None

        job.status_message = status_message
        db.commit()
        db.refresh(job)
        return job


class AudioOverviewCRUD(
    CRUDBase[AudioOverview, AudioOverviewCreate, AudioOverviewUpdate]
):
    """CRUD operations for AudioOverview model"""

    def create(
        self,
        db: Session,
        *,
        obj_in: AudioOverviewCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> AudioOverview | None:
        """Create a new audio overview"""
        if user is None:
            raise ValueError("User must be provided to create an audio overview")
        obj_in_data = obj_in.model_dump(exclude_unset=True)
        db_obj = AudioOverview(**obj_in_data, user_id=user.id)

        db.add(db_obj)
        if auto_commit:
            db.commit()
            db.refresh(db_obj)
        else:
            db.flush()
        return db_obj

    def get_by_conversable_and_user(
        self,
        db: Session,
        *,
        conversable_id: UUID,
        conversable_type: ConversableType,
        current_user: CurrentUser,
    ) -> list[AudioOverview] | None:
        """Get audio overviews by conversable ID, type and user"""
        if conversable_type == ConversableType.PAPER:
            # For papers, check direct ownership
            return list(
                db.scalars(
                    select(AudioOverview)
                    .where(
                        AudioOverview.conversable_id == conversable_id,
                        AudioOverview.conversable_type == conversable_type,
                        AudioOverview.user_id == current_user.id,
                    )
                    .order_by(AudioOverview.created_at.desc())
                ).all()
            )
        elif conversable_type == ConversableType.PROJECT:
            # For projects, check user has project access through ProjectRole
            return list(
                db.scalars(
                    select(AudioOverview)
                    .join(Project, AudioOverview.conversable_id == Project.id)
                    .join(ProjectRole, Project.id == ProjectRole.project_id)
                    .where(
                        AudioOverview.conversable_id == conversable_id,
                        AudioOverview.conversable_type == conversable_type,
                        ProjectRole.user_id == current_user.id,
                    )
                    .order_by(AudioOverview.created_at.desc())
                ).all()
            )

        # Fallback to direct ownership for other types
        return list(
            db.scalars(
                select(AudioOverview)
                .where(
                    AudioOverview.conversable_id == conversable_id,
                    AudioOverview.conversable_type == conversable_type,
                    AudioOverview.user_id == current_user.id,
                )
                .order_by(AudioOverview.created_at.desc())
            ).all()
        )

    def get_mrc_by_conversable_and_user(
        self,
        db: Session,
        *,
        conversable_id: UUID,
        conversable_type: ConversableType,
        current_user: CurrentUser,
    ) -> AudioOverview | None:
        """Get the most recent audio overview by conversable ID, type and user"""
        return db.scalars(
            select(AudioOverview)
            .where(
                AudioOverview.conversable_id == conversable_id,
                AudioOverview.conversable_type == conversable_type,
                AudioOverview.user_id == current_user.id,
            )
            .order_by(AudioOverview.created_at.desc())
        ).first()

    def get_by_id_project_and_user(
        self, db: Session, *, id: UUID, project_id: UUID, current_user: CurrentUser
    ) -> AudioOverview | None:
        """Get audio overview by ID, project ID and user - ensures user has project access"""
        return db.scalars(
            select(AudioOverview)
            .join(Project, AudioOverview.conversable_id == Project.id)
            .join(ProjectRole, Project.id == ProjectRole.project_id)
            .where(
                AudioOverview.id == id,
                AudioOverview.conversable_id == project_id,
                AudioOverview.conversable_type == ConversableType.PROJECT,
                ProjectRole.user_id == current_user.id,
            )
        ).first()

    def get_user_overviews(
        self,
        db: Session,
        *,
        current_user: CurrentUser,
        conversable_type: ConversableType | None = None,
    ) -> list[AudioOverview]:
        """Get all audio overviews for a user, optionally filtered by type"""
        statement = select(AudioOverview).where(
            AudioOverview.user_id == current_user.id
        )

        if conversable_type:
            statement = statement.where(
                AudioOverview.conversable_type == conversable_type
            )

        return list(
            db.scalars(statement.order_by(AudioOverview.created_at.desc())).all()
        )

    def update_transcript(
        self,
        db: Session,
        *,
        overview_id: UUID,
        transcript: str,
        current_user: CurrentUser,
    ) -> AudioOverview | None:
        """Update the transcript for an audio overview"""
        overview = db.scalars(
            select(AudioOverview).where(
                AudioOverview.id == overview_id,
                AudioOverview.user_id == current_user.id,
            )
        ).first()

        if not overview:
            return None

        overview.transcript = transcript
        db.commit()
        db.refresh(overview)
        return overview


# Create single instances to use throughout the application
audio_overview_job_crud = AudioOverviewJobCRUD(AudioOverviewJob)
audio_overview_crud = AudioOverviewCRUD(AudioOverview)
