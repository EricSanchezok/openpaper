import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.auth.dependencies import get_required_user
from app.database.crud.projects.project_data_table_crud import (
    DataTableJobCreate,
    data_table_job_crud,
    data_table_result_crud,
)
from app.database.crud.projects.project_paper_crud import project_paper_crud
from app.database.database import get_db
from app.database.models import JobStatus
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency,
    release_concurrency_by_id,
)
from app.helpers.pdf_jobs import jobs_client
from app.llm.conversation_operations import data_table_operations
from app.llm.token_credits import has_token_credits, llm_usage_context
from app.schemas.responses import DataTableSchema, DocumentMapping
from app.schemas.user import CurrentUser
from app.schemas.orm_responses import (
    serialize_data_table_job,
    serialize_data_table_result,
)
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Maximum time a data table job can run before being marked as failed
MAX_DATA_TABLES_JOB_RUNTIME = timedelta(hours=1)

# Create API router
projects_data_table_router = APIRouter()


class CreateDataTableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    columns: list[str] = Field(min_length=1, max_length=50)

    @field_validator("columns")
    @classmethod
    def validate_columns(_cls, value: list[str]) -> list[str]:
        normalized = [column.strip() for column in value]
        if any(not column or len(column) > 200 for column in normalized):
            raise ValueError("Columns must contain 1-200 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Columns must be unique")
        return normalized


class ProposeDataTableSchemaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: uuid.UUID
    prompt: str = Field(min_length=1, max_length=10_000)


@projects_data_table_router.post("/propose")
async def propose_data_table_schema(
    request: ProposeDataTableSchemaRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Propose data table columns from a natural language description of what
    the user wants to extract from the project's papers.
    """
    try:
        prompt = request.prompt.strip()
        if not prompt:
            return JSONResponse(
                status_code=400,
                content={"message": "Prompt must not be empty"},
            )

        project_papers = project_paper_crud.get_all_papers_by_project_id(
            db, project_id=request.project_id, user=current_user
        )

        paper_titles = [str(pp.title) for pp in project_papers if pp.title]

        if not has_token_credits(db, user=current_user):
            return JSONResponse(
                status_code=429, content={"code": "token_quota_exceeded"}
            )

        try:
            await enforce_rate_limit(
                user_id=int(current_user.id),
                ip_address=(
                    http_request.client.host if http_request.client else "unknown"
                ),
                feature="data_table",
            )
            lease = await acquire_concurrency(
                user_id=int(current_user.id), category="interactive"
            )
        except AILimitExceeded as exc:
            return JSONResponse(status_code=429, content={"code": exc.code})
        try:
            with llm_usage_context(
                user_id=int(current_user.id), feature="data_table_proposal"
            ):
                columns = data_table_operations.propose_data_table_schema(
                    prompt=prompt,
                    paper_titles=paper_titles,
                )
        finally:
            await release_concurrency(lease)

        if not columns:
            return JSONResponse(
                status_code=500,
                content={"message": "Failed to propose data table schema"},
            )

        return JSONResponse(
            status_code=200,
            content={"columns": columns},
        )
    except Exception:
        logger.exception("Error proposing data table schema")
        return JSONResponse(
            status_code=400,
            content={"code": "data_table_proposal_failed"},
        )


@projects_data_table_router.post("")
async def create_data_table(
    request: CreateDataTableRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Create a data table extraction job for a project.
    """
    job = None
    lease_acquired = False
    try:
        if not has_token_credits(db, user=current_user):
            return JSONResponse(
                status_code=429,
                content={"code": "token_quota_exceeded"},
            )
        try:
            await enforce_rate_limit(
                user_id=int(current_user.id),
                ip_address=(
                    http_request.client.host if http_request.client else "unknown"
                ),
                feature="data_table",
            )
        except AILimitExceeded as exc:
            return JSONResponse(status_code=429, content={"code": exc.code})

        papers: list[DocumentMapping] = []

        project_papers = project_paper_crud.get_all_papers_by_project_id(
            db, project_id=request.project_id, user=current_user
        )

        for pp in project_papers:
            papers.append(
                DocumentMapping(
                    id=str(pp.id),
                    title=str(pp.title),
                    raw_content=str(pp.raw_content or ""),
                )
            )

        # Create the job in the database first
        job = data_table_job_crud.create(
            db=db,
            obj_in=DataTableJobCreate(
                project_id=request.project_id,
                columns=request.columns,
            ),
            user=current_user,
        )

        if not job:
            return JSONResponse(
                status_code=403,
                content={
                    "message": "Failed to create data table job - permission denied"
                },
            )

        job_id = str(job.id)
        try:
            await acquire_concurrency(
                user_id=int(current_user.id),
                category="background",
                operation_id=job_id,
            )
            lease_acquired = True
        except AILimitExceeded as exc:
            data_table_job_crud.update_status(
                db=db,
                job_id=uuid.UUID(str(job.id)),
                status=JobStatus.FAILED,
                error_message=exc.code,
            )
            return JSONResponse(status_code=429, content={"code": exc.code})

        data_table = DataTableSchema(
            columns=request.columns,
            papers=papers,
        )

        # Submit the data table processing job
        task_id = jobs_client.submit_data_table_processing_job(
            data_table=data_table,
            job_id=job_id,
        )

        # Update status to running
        data_table_job_crud.update_status(
            db=db,
            job_id=uuid.UUID(job_id),
            status=JobStatus.RUNNING,
        )

        # Update the job with the task ID
        data_table_job_crud.update_task_id(
            db=db,
            job_id=uuid.UUID(job_id),
            task_id=task_id,
        )

        return JSONResponse(
            status_code=202,
            content={
                "message": "Data table processing job submitted",
                "id": job_id,
                "task_id": task_id,
            },
        )
    except Exception:
        if lease_acquired and job is not None:
            await release_concurrency_by_id(
                user_id=int(current_user.id),
                category="background",
                operation_id=str(job.id),
            )
        logger.exception("Error creating data table job")
        return JSONResponse(
            status_code=400,
            content={"code": "data_table_creation_failed"},
        )


@projects_data_table_router.get("/jobs/{project_id}")
async def list_data_table_jobs(
    project_id: str,
    all: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    List all pending data table extraction jobs for a given project.
    """
    try:
        jobs = data_table_job_crud.get_by_project(
            db=db,
            project_id=uuid.UUID(project_id),
            user=current_user,
        )

        # Check and update status for pending/running jobs
        for job in jobs:
            if (
                job.status not in (JobStatus.COMPLETED, JobStatus.FAILED)
                and job.task_id
            ):
                try:
                    celery_status = jobs_client.check_celery_task_status(
                        str(job.task_id)
                    )
                    celery_status_str = celery_status.get("status", "").lower()

                    if celery_status_str == JobStatus.FAILED:
                        # Celery task failed - update job status to match
                        job = (
                            data_table_job_crud.update_status(
                                db=db,
                                job_id=uuid.UUID(str(job.id)),
                                status=JobStatus.FAILED,
                            )
                            or job
                        )
                        await release_concurrency_by_id(
                            user_id=int(current_user.id),
                            category="background",
                            operation_id=str(job.id),
                        )
                    else:
                        job_age = datetime.now(timezone.utc) - (
                            job.created_at or datetime.now(timezone.utc)
                        )

                        # If job has been running longer than max runtime and Celery still shows running,
                        # assume it's lost and mark as failed
                        if (
                            job_age > MAX_DATA_TABLES_JOB_RUNTIME
                            and celery_status_str == JobStatus.RUNNING
                        ):
                            job = (
                                data_table_job_crud.update_status(
                                    db=db,
                                    job_id=uuid.UUID(str(job.id)),
                                    status=JobStatus.FAILED,
                                )
                                or job
                            )
                            await release_concurrency_by_id(
                                user_id=int(current_user.id),
                                category="background",
                                operation_id=str(job.id),
                            )
                except Exception as e:
                    logger.warning(
                        f"Failed to check Celery task status for {job.task_id}: {e}"
                    )

        if not all:
            # Filter out failed jobs from more than 1 hour ago
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            jobs = [
                job
                for job in jobs
                if not (
                    job.status == JobStatus.FAILED
                    and job.started_at is not None
                    and job.started_at < one_hour_ago
                )
            ]

        job_list = [serialize_data_table_job(job) for job in jobs]

        return JSONResponse(
            status_code=200,
            content={"jobs": job_list},
        )
    except Exception as e:
        logger.error(f"Error listing data table jobs: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to list data table jobs"},
        )


@projects_data_table_router.get("/{job_id}")
async def get_data_table_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get the status of a data table extraction job, including real-time Celery task status.
    """
    try:
        job = data_table_job_crud.get(
            db=db,
            id=uuid.UUID(job_id),
            user=current_user,
        )

        if not job:
            return JSONResponse(
                status_code=404,
                content={"message": "Data table job not found"},
            )

        # Get real-time Celery task status if we have a task_id and job is still in progress
        # (completed/failed jobs no longer have active Celery tasks)
        celery_task_status = None
        if job.task_id and job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
            try:
                celery_task_status = jobs_client.check_celery_task_status(
                    str(job.task_id)
                )
            except Exception as e:
                logger.warning(
                    f"Failed to get Celery task status for {job.task_id}: {e}"
                )

        if celery_task_status:
            celery_status_str = celery_task_status.get("status", "").lower()

            if celery_status_str == JobStatus.FAILED:
                # Celery task failed - update job status to match
                job = (
                    data_table_job_crud.update_status(
                        db=db, job_id=uuid.UUID(str(job.id)), status=JobStatus.FAILED
                    )
                    or job
                )
                await release_concurrency_by_id(
                    user_id=int(current_user.id),
                    category="background",
                    operation_id=str(job.id),
                )
            else:
                # If job has been running for longer than the max runtime,
                # and Celery has no record of it, assume it's lost
                job_age = datetime.now(timezone.utc) - (
                    job.created_at or datetime.now(timezone.utc)
                )

                if (
                    job_age > MAX_DATA_TABLES_JOB_RUNTIME
                    and celery_status_str == JobStatus.PENDING
                ):
                    # Task is too old to still be pending - it's lost
                    job = (
                        data_table_job_crud.update_status(
                            db=db,
                            job_id=uuid.UUID(str(job.id)),
                            status=JobStatus.FAILED,
                        )
                        or job
                    )
                    await release_concurrency_by_id(
                        user_id=int(current_user.id),
                        category="background",
                        operation_id=str(job.id),
                    )

        # Build response with both job status and task status
        response_content = {
            "job_id": str(job.id),
            "status": job.status,
            "columns": job.columns,
            "task_id": job.task_id,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_message": job.error_message,
        }

        # Add Celery task information if available
        if celery_task_status:
            response_content.update(
                {
                    "celery_status": celery_task_status.get("status"),
                    "celery_progress_message": celery_task_status.get(
                        "progress_message"
                    ),
                    "celery_error": celery_task_status.get("error"),
                }
            )

        return JSONResponse(status_code=200, content=response_content)
    except Exception as e:
        logger.error(f"Error fetching data table job status: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to fetch data table job status"},
        )


@projects_data_table_router.get("/results/{result_id}")
async def get_data_table_job_results(
    result_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get the results of a completed data table extraction job.
    """
    try:
        result = data_table_result_crud.get(
            db=db,
            id=uuid.UUID(result_id),
            user=current_user,
        )

        if not result:
            return JSONResponse(
                status_code=404,
                content={"message": "Data table results not found"},
            )

        data = serialize_data_table_result(result)

        return JSONResponse(
            status_code=200,
            content={"data": data},
        )
    except Exception as e:
        logger.error(f"Error fetching data table job results: {e}")
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to fetch data table job results"},
        )
