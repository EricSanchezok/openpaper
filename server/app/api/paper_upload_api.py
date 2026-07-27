"""
Document Upload API - Microservice Integration

This module handles PDF upload and processing by integrating with a separate
PDF processing microservice. The architecture is:

1. Client uploads PDF to this API
2. API creates a PaperUploadJob record with status 'pending'
3. API submits the PDF to the separate jobs service via Celery/HTTP
4. Jobs service processes PDF (S3 upload, metadata extraction, preview generation)
5. Jobs service sends results back via webhook
6. Webhook handler updates PaperUploadJob status and creates Document record

The client can poll the job status using the same job_id throughout the process.
"""

from starlette.responses import Response as ApiResponse

import logging
from datetime import datetime, timezone
from uuid import UUID

from app.api.jobs_webhooks.router import handle_failed_upload
from app.auth.dependencies import get_required_user
from app.database.crud.paper_crud import paper_crud
from app.database.crud.paper_upload_crud import (
    PaperUploadJobCreate,
    PaperUploadJobUpdate,
    paper_upload_job_crud,
)
from app.database.database import get_db
from app.database.models import AuthUser, JobStatus, PaperUploadJob
from app.database.telemetry import track_event
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency_by_id,
)
from app.helpers.parser import (
    MAX_UPLOAD_SIZE_MB,
    validate_pdf_content,
    validate_url_and_fetch_pdf,
)
from app.helpers.pdf_jobs import jobs_client
from app.helpers.subscription_limits import (
    can_user_access_knowledge_base,
    can_user_add_papers_to_project,
    can_user_upload_paper,
)
from app.policies.projects import get_project_access
from app.schemas.user import CurrentUser
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, HttpUrl
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

# Create API router with prefix
paper_upload_router = APIRouter()


class UploadFromUrlSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


@paper_upload_router.get("/status/{job_id}")
async def get_upload_status(
    job_id: str,
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ApiResponse:
    """
    Get the status of a paper upload job, including real-time Celery task status.
    """
    paper_upload_job = paper_upload_job_crud.get(db=db, id=job_id, user=current_user)

    if not paper_upload_job:
        return JSONResponse(status_code=404, content={"message": "Job not found"})

    paper = paper_crud.get_by_upload_job_id(
        db=db, upload_job_id=str(paper_upload_job.id), user=current_user
    )

    if paper_upload_job.status == JobStatus.COMPLETED:
        # Verify the paper exists
        if not paper:
            return JSONResponse(status_code=404, content={"message": "Paper not found"})

    # Get real-time Celery task status if we have a task_id and job is still in progress
    # (completed/failed jobs no longer have active Celery tasks)
    celery_task_status = None
    if paper_upload_job.task_id and paper_upload_job.status not in (
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    ):
        try:
            celery_task_status = jobs_client.check_celery_task_status(
                str(paper_upload_job.task_id)
            )
        except Exception as e:
            logger.warning(
                f"Failed to get Celery task status for {paper_upload_job.task_id}: {e}"
            )

    # If Celery reports failure, clean up and update the job status to match
    if (
        celery_task_status
        and celery_task_status.get("status", "").lower() == JobStatus.FAILED
    ):
        handle_failed_upload(
            db=db,
            job_id=str(paper_upload_job.id),
            job_user=current_user,
            reason=celery_task_status.get("error", "Celery task failed"),
        )

    # Build response with both job status and task status
    response_content = {
        "job_id": str(paper_upload_job.id),
        "status": paper_upload_job.status,
        "task_id": paper_upload_job.task_id,
        "started_at": (
            paper_upload_job.started_at.isoformat()
            if paper_upload_job.started_at
            else None
        ),
        "completed_at": (
            paper_upload_job.completed_at.isoformat()
            if paper_upload_job.completed_at
            else None
        ),
        "has_file_url": bool(paper.file_url) if paper else False,
        "has_metadata": bool(paper.abstract) if paper else False,
        "paper_id": str(paper.id) if paper else None,
        "parser_quality": paper.parser_quality if paper else None,
        "parser_warning_code": paper.parser_warning_code if paper else None,
    }

    # Add Celery task information if available
    if celery_task_status:
        response_content.update(
            {
                "celery_status": celery_task_status.get("status"),
                "celery_progress_message": celery_task_status.get("progress_message"),
                "celery_error": celery_task_status.get("error"),
            }
        )

    return JSONResponse(status_code=200, content=response_content)


@paper_upload_router.post("/from-url/")
async def upload_pdf_from_url(
    request: UploadFromUrlSchema,
    http_request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
    project_id: UUID | None = None,
) -> ApiResponse:
    """
    Upload a document from a given URL, rather than the raw file.
    """
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=http_request.client.host if http_request.client else "unknown",
            feature="upload",
        )
    except AILimitExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": exc.code}) from None

    # Check subscription limits before proceeding
    err_message = await check_subscription_limits(current_user, db, project_id)
    if err_message:
        return JSONResponse(
            status_code=403,
            content={
                "message": err_message,
                "error_code": "SUBSCRIPTION_LIMIT_EXCEEDED",
            },
        )

    # Validate the URL and fetch PDF content
    url = str(request.url)
    is_valid, pdf_bytes, error_message = await validate_url_and_fetch_pdf(url)
    if not is_valid:
        return JSONResponse(status_code=400, content={"message": error_message})

    # Create the paper upload job
    paper_upload_job_obj = PaperUploadJobCreate(
        started_at=datetime.now(timezone.utc),
    )

    paper_upload_job = paper_upload_job_crud.create(
        db=db,
        obj_in=paper_upload_job_obj,
        user=current_user,
    )

    if not paper_upload_job:
        return JSONResponse(
            status_code=500,
            content={"message": "Failed to create paper upload job"},
        )
    try:
        await acquire_concurrency(
            user_id=int(current_user.id),
            category="background",
            operation_id=str(paper_upload_job.id),
        )
    except AILimitExceeded as exc:
        paper_upload_job_crud.mark_as_failed(
            db=db, job_id=str(paper_upload_job.id), user=current_user
        )
        raise HTTPException(status_code=429, detail={"code": exc.code}) from None

    # Get filename from URL
    filename = url.split("/")[-1]

    # Pass file contents and filename instead of the UploadFile object
    background_tasks.add_task(
        upload_raw_file_microservice,
        file_contents=pdf_bytes,
        filename=filename,
        paper_upload_job=paper_upload_job,
        current_user=current_user,
        db=db,
        project_id=project_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "message": "File upload started",
            "job_id": str(paper_upload_job.id),
        },
    )


@paper_upload_router.post("/")
async def upload_pdf(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
    project_id: UUID | None = None,
) -> ApiResponse:
    """
    Upload a PDF file
    """
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=request.client.host if request.client else "unknown",
            feature="upload",
        )
    except AILimitExceeded as exc:
        raise HTTPException(status_code=429, detail={"code": exc.code}) from None
    # Check subscription limits before proceeding
    err_message = await check_subscription_limits(current_user, db, project_id)
    if err_message:
        return JSONResponse(
            status_code=403,
            content={
                "message": err_message,
                "error_code": "SUBSCRIPTION_LIMIT_EXCEEDED",
            },
        )

    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    declared_size = request.headers.get("content-length")
    if declared_size and (
        not declared_size.isdigit() or int(declared_size) > max_bytes + 1024 * 1024
    ):
        return JSONResponse(
            status_code=413,
            content={"message": f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)"},
        )
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        return JSONResponse(
            status_code=400,
            content={"message": "Uploaded file must use a PDF content type"},
        )

    # Starlette spools multipart files, but an explicit running cap prevents an
    # unbounded application-level read when Content-Length is absent or false.
    try:
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(65536):
            total += len(chunk)
            if total > max_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"message": f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)"},
                )
            chunks.append(chunk)
        file_contents = b"".join(chunks)
        filename = file.filename
    except Exception:
        logger.exception("Error reading uploaded file")
        return JSONResponse(
            status_code=400, content={"message": "Error reading uploaded file"}
        )

    # Validate PDF content
    is_valid, error_message = await validate_pdf_content(file_contents, source="upload")
    if not is_valid:
        return JSONResponse(status_code=400, content={"message": error_message})

    # Create the paper upload job
    paper_upload_job_obj = PaperUploadJobCreate(
        started_at=datetime.now(timezone.utc),
    )

    paper_upload_job = paper_upload_job_crud.create(
        db=db,
        obj_in=paper_upload_job_obj,
        user=current_user,
    )

    if not paper_upload_job:
        return JSONResponse(
            status_code=500,
            content={"message": "Failed to create paper upload job"},
        )
    try:
        await acquire_concurrency(
            user_id=int(current_user.id),
            category="background",
            operation_id=str(paper_upload_job.id),
        )
    except AILimitExceeded as exc:
        paper_upload_job_crud.mark_as_failed(
            db=db, job_id=str(paper_upload_job.id), user=current_user
        )
        raise HTTPException(status_code=429, detail={"code": exc.code}) from None

    # Pass file contents and filename instead of the UploadFile object
    background_tasks.add_task(
        upload_raw_file_microservice,
        file_contents=file_contents,
        filename=str(filename),
        paper_upload_job=paper_upload_job,
        current_user=current_user,
        db=db,
        project_id=project_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "message": "File upload started",
            "job_id": str(paper_upload_job.id),
        },
    )


async def check_subscription_limits(
    current_user: CurrentUser,
    db: Session,
    project_id: UUID | None = None,
) -> str | None:
    """
    Check resource quotas against the account that owns the destination.

    Personal uploads are billed to the caller. Project uploads are authorized
    using the caller's delegated capability but billed to the Project owner.
    """
    if project_id:
        access = get_project_access(
            db,
            project_id=project_id,
            user_id=current_user.id,
        )
        if access is None:
            return "Project not found"
        if not access.can_manage_papers:
            return "You do not have permission to add papers to this project"
        can_add, error_message = can_user_add_papers_to_project(
            db, current_user, project_id=project_id, paper_count=1
        )
        if not can_add and error_message:
            return error_message
        owner = db.get(AuthUser, access.project.owner_id)
        if owner is None:
            raise RuntimeError(f"Project {project_id} has no owner")
        quota_user = CurrentUser.from_auth_user(owner)
    else:
        quota_user = current_user

    can_upload, error_message = can_user_upload_paper(db, quota_user)
    if not can_upload and error_message:
        return error_message

    can_access, error_message = can_user_access_knowledge_base(db, quota_user)
    if not can_access and error_message:
        return error_message

    return None


async def upload_raw_file_microservice(
    file_contents: bytes,
    filename: str,
    paper_upload_job: PaperUploadJob,
    current_user: CurrentUser,
    db: Session,
    project_id: UUID | None = None,
) -> None:
    """
    Helper function to upload a raw file using the microservice.
    """

    paper_upload_job_crud.mark_as_running(
        db=db,
        job_id=str(paper_upload_job.id),
        user=current_user,
    )

    try:
        # Submit to microservice
        task_id = await jobs_client.submit_pdf_processing_job_with_upload(
            pdf_bytes=file_contents,
            paper_upload_job=paper_upload_job,
            db=db,
            user=current_user,
            project_id=project_id,
            original_filename=filename,
        )

        # Update job with task_id
        paper_upload_job_crud.update(
            db=db,
            db_obj=paper_upload_job,
            obj_in=PaperUploadJobUpdate(task_id=task_id),
            user=current_user,
        )

        # Track paper upload event
        track_event(
            "paper_upload_submitted_to_microservice",
            properties={
                "task_id": task_id,
            },
            user_id=str(current_user.id),
            db=db,
        )

    except Exception:
        logger.error("Error submitting file to microservice", exc_info=True)
        paper_upload_job_crud.mark_as_failed(
            db=db,
            job_id=str(paper_upload_job.id),
            user=current_user,
        )
        await release_concurrency_by_id(
            user_id=int(current_user.id),
            category="background",
            operation_id=str(paper_upload_job.id),
        )
