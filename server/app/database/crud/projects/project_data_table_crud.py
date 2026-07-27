import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app.database.crud.base_crud import CRUDBase
from app.database.crud.sanitization import sanitize_for_postgres
from app.database.models import (
    DataTableExtractionJob,
    DataTableExtractionResult,
    DataTableRow,
    JobStatus,
)
from app.policies.projects import get_project_access
from app.repositories.projects import project_repository
from app.database.telemetry import track_event
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

logger = logging.getLogger(__name__)


# ================================
# Job Schemas
# ================================


class DataTableJobCreate(BaseModel):
    project_id: UUID
    columns: list[str]
    task_id: str | None = None
    is_shared: bool = True


class DataTableJobUpdate(BaseModel):
    status: str | None = None
    task_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


# ================================
# Result Schemas
# ================================


class DataTableResultCreate(BaseModel):
    job_id: UUID
    title: str
    success: bool
    columns: list[str]
    row_failures: list[UUID] = []


class DataTableResultUpdate(BaseModel):
    success: bool | None = None
    columns: list[str] | None = None


class DataTableRowCreate(BaseModel):
    data_table_id: UUID
    paper_id: UUID
    values: dict[str, Any]  # {column_name: {value: str, citations: [...]}}


class DataTableRowUpdate(BaseModel):
    values: dict[str, Any] | None = None


# ================================
# Job CRUD
# ================================


class DataTableJobCRUD(
    CRUDBase[DataTableExtractionJob, DataTableJobCreate, DataTableJobUpdate]
):
    """CRUD operations for DataTableExtractionJob model"""

    def create(
        self,
        db: Session,
        *,
        obj_in: DataTableJobCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> DataTableExtractionJob | None:
        """Create a new data table extraction job"""
        if user is None:
            raise ValueError("User must be provided to create a data table job")
        # Check if user has access to the project
        if (
            get_project_access(db, project_id=obj_in.project_id, user_id=user.id)
            is None
        ):
            logger.warning(
                f"User {user.id} does not have permission to create job in project {obj_in.project_id}"
            )
            return None

        try:
            db_obj = DataTableExtractionJob(
                user_id=user.id,
                project_id=obj_in.project_id,
                columns=obj_in.columns,
                task_id=obj_in.task_id,
                status=JobStatus.PENDING,
                is_shared=obj_in.is_shared,
            )
            db.add(db_obj)
            if auto_commit:
                db.commit()
                db.refresh(db_obj)
            else:
                db.flush()

            # Touch project updated_at so it sorts to top of recent projects
            project_repository.touch(
                db, project_id=obj_in.project_id, commit=auto_commit
            )

            track_event(
                "data_table_job_created",
                properties={
                    "job_id": str(db_obj.id),
                    "project_id": str(obj_in.project_id),
                    "num_columns": len(obj_in.columns),
                    "columns": obj_in.columns,
                },
                user_id=str(user.id),
                db=db,
            )

            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error creating DataTableExtractionJob: {str(e)}", exc_info=True
            )
            return None

    def get_data_table_jobs_used_this_week(
        self,
        db: Session,
        *,
        user: CurrentUser,
    ) -> int:
        """Get the number of data table jobs created by the user in the current week"""
        start_of_week = datetime.now(timezone.utc)
        start_of_week -= timedelta(days=start_of_week.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

        count = db.scalar(
            select(func.count(DataTableExtractionJob.id)).where(
                DataTableExtractionJob.user_id == user.id,
                DataTableExtractionJob.created_at >= start_of_week,
            )
        )
        return int(count or 0)

    def get_by_project(
        self,
        db: Session,
        *,
        project_id: UUID,
        user: CurrentUser,
    ) -> list[DataTableExtractionJob]:
        """Get all data table jobs for a project with their associated results"""
        access = get_project_access(db, project_id=project_id, user_id=user.id)
        if access is None:
            return []

        statement = (
            select(DataTableExtractionJob)
            .options(
                joinedload(DataTableExtractionJob.result),
                joinedload(DataTableExtractionJob.user),
            )
            .where(DataTableExtractionJob.project_id == project_id)
        )
        if not access.is_owner:
            statement = statement.where(
                DataTableExtractionJob.is_shared.is_(True)
                | (DataTableExtractionJob.user_id == user.id)
            )
        return list(
            db.scalars(statement.order_by(DataTableExtractionJob.created_at.desc()))
            .unique()
            .all()
        )

    def get_pending_by_project(
        self,
        db: Session,
        *,
        project_id: UUID,
        user: CurrentUser,
    ) -> list[DataTableExtractionJob]:
        """Get all pending data table jobs for a project"""
        access = get_project_access(db, project_id=project_id, user_id=user.id)
        if access is None:
            return []

        statement = (
            select(DataTableExtractionJob)
            .options(joinedload(DataTableExtractionJob.user))
            .where(
                DataTableExtractionJob.project_id == project_id,
                DataTableExtractionJob.status == JobStatus.PENDING,
            )
        )
        if not access.is_owner:
            statement = statement.where(
                DataTableExtractionJob.is_shared.is_(True)
                | (DataTableExtractionJob.user_id == user.id)
            )
        return list(
            db.scalars(
                statement.order_by(DataTableExtractionJob.created_at.desc())
            ).all()
        )

    def get_by_id_and_project(
        self,
        db: Session,
        *,
        job_id: UUID,
        project_id: UUID,
        user: CurrentUser,
    ) -> DataTableExtractionJob | None:
        """Get a specific job by ID within a project"""
        access = get_project_access(db, project_id=project_id, user_id=user.id)
        if access is None:
            return None

        statement = (
            select(DataTableExtractionJob)
            .options(joinedload(DataTableExtractionJob.user))
            .where(
                DataTableExtractionJob.id == job_id,
                DataTableExtractionJob.project_id == project_id,
            )
        )
        if not access.is_owner:
            statement = statement.where(
                DataTableExtractionJob.is_shared.is_(True)
                | (DataTableExtractionJob.user_id == user.id)
            )
        return db.scalars(statement).first()

    def get_by_task_id(
        self,
        db: Session,
        *,
        task_id: str,
    ) -> DataTableExtractionJob | None:
        """Get a job by its Celery task ID (for webhook handlers)"""
        return db.scalars(
            select(DataTableExtractionJob).where(
                DataTableExtractionJob.task_id == task_id
            )
        ).first()

    def update_status(
        self,
        db: Session,
        *,
        job_id: UUID,
        status: str,
        error_message: str | None = None,
    ) -> DataTableExtractionJob | None:
        """Update job status with timestamp tracking"""
        job = db.get(DataTableExtractionJob, job_id)

        if not job:
            return None

        job.status = status

        now = datetime.now(timezone.utc)

        # Set timestamps based on status
        if status == JobStatus.RUNNING and not job.started_at:
            job.started_at = now
        elif status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            if not job.completed_at:
                job.completed_at = now

        if error_message:
            job.error_message = error_message

        db.commit()
        db.refresh(job)

        # Track completion/failure telemetry
        time_elapsed = (
            (now - job.created_at).total_seconds() if job.created_at else None
        )

        if status == JobStatus.COMPLETED:
            track_event(
                "data_table_completed",
                properties={
                    "job_id": str(job_id),
                    "project_id": str(job.project_id),
                    "num_columns": len(job.columns) if job.columns else 0,
                    "time_to_completion_seconds": time_elapsed,
                },
                user_id=str(job.user_id),
                db=db,
            )
        elif status == JobStatus.FAILED:
            track_event(
                "data_table_failed",
                properties={
                    "job_id": str(job_id),
                    "project_id": str(job.project_id),
                    "time_elapsed_seconds": time_elapsed,
                    "error_message": (error_message or "")[:200],
                },
                user_id=str(job.user_id),
                db=db,
            )

        return job

    def update_task_id(
        self,
        db: Session,
        *,
        job_id: UUID,
        task_id: str,
    ) -> DataTableExtractionJob | None:
        """Update the Celery task ID for a job"""
        job = db.get(DataTableExtractionJob, job_id)

        if not job:
            return None

        job.task_id = task_id
        db.commit()
        db.refresh(job)
        return job


# ================================
# Result CRUD
# ================================


class DataTableResultCRUD(
    CRUDBase[DataTableExtractionResult, DataTableResultCreate, DataTableResultUpdate]
):
    """CRUD operations for DataTableExtractionResult model"""

    def create(
        self,
        db: Session,
        *,
        obj_in: DataTableResultCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> DataTableExtractionResult | None:
        """Create a new data table result"""
        try:
            db_obj = DataTableExtractionResult(
                title=obj_in.title,
                job_id=obj_in.job_id,
                success=obj_in.success,
                columns=obj_in.columns,
                row_failures=obj_in.row_failures,
            )
            db.add(db_obj)
            if auto_commit:
                db.commit()
                db.refresh(db_obj)
            else:
                db.flush()

            track_event(
                "data_table_result_created",
                properties={
                    "job_id": str(obj_in.job_id),
                    "result_id": str(db_obj.id),
                    "num_columns": len(obj_in.columns),
                    "success": obj_in.success,
                    "num_row_failures": len(obj_in.row_failures),
                },
                user_id=str(user.id) if user else None,
                db=db,
            )

            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error creating DataTableExtractionResult: {str(e)}", exc_info=True
            )
            return None

    def get_by_job_id(
        self,
        db: Session,
        *,
        job_id: UUID,
    ) -> DataTableExtractionResult | None:
        """Get result by job ID with rows eagerly loaded"""
        return (
            db.scalars(
                select(DataTableExtractionResult)
                .options(joinedload(DataTableExtractionResult.rows))
                .where(DataTableExtractionResult.job_id == job_id)
            )
            .unique()
            .first()
        )

    def get_by_project(
        self,
        db: Session,
        *,
        project_id: UUID,
        user: CurrentUser,
    ) -> list[DataTableExtractionResult]:
        """Get all results for a project"""
        if get_project_access(db, project_id=project_id, user_id=user.id) is None:
            return []

        return list(
            db.scalars(
                select(DataTableExtractionResult)
                .join(
                    DataTableExtractionJob,
                    DataTableExtractionResult.job_id == DataTableExtractionJob.id,
                )
                .where(DataTableExtractionJob.project_id == project_id)
                .where(
                    DataTableExtractionJob.is_shared.is_(True)
                    | (DataTableExtractionJob.user_id == user.id)
                )
                .order_by(DataTableExtractionResult.created_at.desc())
            ).all()
        )


# ================================
# Row CRUD
# ================================


class DataTableRowCRUD(CRUDBase[DataTableRow, DataTableRowCreate, DataTableRowUpdate]):
    """CRUD operations for DataTableRow model"""

    def create(
        self,
        db: Session,
        *,
        obj_in: DataTableRowCreate,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> DataTableRow | None:
        """Create a new data table row.

        Values are sanitized to remove null characters that PostgreSQL cannot store.
        """
        try:
            db_obj = DataTableRow(
                data_table_id=obj_in.data_table_id,
                paper_id=obj_in.paper_id,
                values=sanitize_for_postgres(obj_in.values),
            )
            db.add(db_obj)
            if auto_commit:
                db.commit()
                db.refresh(db_obj)
            else:
                db.flush()
            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating DataTableRow: {str(e)}", exc_info=True)
            return None

    def create_many(
        self,
        db: Session,
        *,
        rows: list[DataTableRowCreate],
    ) -> list[DataTableRow]:
        """Create multiple data table rows in a single transaction.

        Values are sanitized to remove null characters (\\u0000) that PostgreSQL
        cannot store in text/JSONB columns. This is common when processing
        data extracted from PDFs.
        """
        try:
            db_objs = [
                DataTableRow(
                    data_table_id=row.data_table_id,
                    paper_id=row.paper_id,
                    values=sanitize_for_postgres(row.values),
                )
                for row in rows
            ]
            db.add_all(db_objs)
            db.commit()
            for obj in db_objs:
                db.refresh(obj)

            track_event(
                "data_table_rows_created",
                properties={
                    "data_table_id": str(rows[0].data_table_id) if rows else None,
                    "num_rows": len(db_objs),
                },
                db=db,
            )

            return db_objs
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating DataTableRows: {str(e)}", exc_info=True)
            return []

    def get_by_data_table(
        self,
        db: Session,
        *,
        data_table_id: UUID,
    ) -> list[DataTableRow]:
        """Get all rows for a data table result"""
        return list(
            db.scalars(
                select(DataTableRow).where(DataTableRow.data_table_id == data_table_id)
            ).all()
        )


# Create single instances to use throughout the application
data_table_job_crud = DataTableJobCRUD(DataTableExtractionJob)
data_table_result_crud = DataTableResultCRUD(DataTableExtractionResult)
data_table_row_crud = DataTableRowCRUD(DataTableRow)
