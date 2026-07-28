"""
Document Upload API - Microservice Integration

This module handles PDF upload and processing by integrating with a separate
PDF processing microservice. The architecture is:

1. Client uploads PDF to this API
2. API creates a UploadReservation record with status 'pending'
3. API submits the PDF to the separate jobs service via Celery/HTTP
4. Jobs service processes PDF (S3 upload, metadata extraction, preview generation)
5. Jobs service sends results back via webhook
6. Webhook handler updates UploadReservation status and creates Document record

The client can poll the job status using the same job_id throughout the process.
"""

from starlette.responses import Response as ApiResponse
from starlette.concurrency import run_in_threadpool

import logging
import hashlib
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
from uuid import UUID

from app.auth.dependencies import get_required_user
from app.repositories.documents import document_repository
from app.repositories.upload_reservations import upload_reservation_repository
from app.database.database import get_db
from app.database.models import JobStatus, UploadReservation
from app.database.telemetry import track_event
from app.errors import AppError
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
from app.schemas.user import CurrentUser
from app.schemas.uploads import UploadFromUrlRequest
from app.services.document_submission import submit_reserved_document
from app.services.upload_reservations import reserve_upload
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

# Create API router with prefix
paper_upload_router = APIRouter()


@paper_upload_router.get("/status/{job_id}")
async def get_upload_status(
    job_id: str,
    current_user: CurrentUser = Depends(get_required_user),
    db: Session = Depends(get_db),
) -> ApiResponse:
    """
    Get the durable status of a paper ingestion from PostgreSQL.
    """
    paper_upload_job = upload_reservation_repository.get(
        db=db, id=job_id, user=current_user
    )

    if not paper_upload_job:
        return JSONResponse(status_code=404, content={"message": "Job not found"})

    paper = document_repository.find_by_upload_job(
        db=db, upload_job_id=str(paper_upload_job.id), user=current_user
    )

    durable_job = paper_upload_job.job
    if durable_job.status == JobStatus.COMPLETED:
        # Verify the paper exists
        if not paper:
            return JSONResponse(status_code=404, content={"message": "Paper not found"})

    # Build response with both job status and task status
    response_content = {
        "job_id": str(paper_upload_job.id),
        "status": durable_job.status,
        "task_id": str(durable_job.id) if durable_job.dispatch is not None else None,
        "started_at": (
            durable_job.started_at.isoformat() if durable_job.started_at else None
        ),
        "completed_at": (
            durable_job.completed_at.isoformat() if durable_job.completed_at else None
        ),
        "has_file": bool(paper.s3_object_key) if paper else False,
        "has_metadata": bool(paper.abstract) if paper else False,
        "paper_id": str(paper.id) if paper else None,
        "parser_quality": paper.parser_quality if paper else None,
        "parser_warning_code": paper.parser_warning_code if paper else None,
    }

    response_content.update(
        {
            "progress_message": durable_job.progress_message,
            "error_code": durable_job.error_code,
        }
    )

    return JSONResponse(status_code=200, content=response_content)


@paper_upload_router.post("/from-url/")
async def upload_pdf_from_url(
    request: UploadFromUrlRequest,
    http_request: Request,
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

    # Validate the URL and fetch PDF content
    url = str(request.url)
    is_valid, pdf_bytes, error_message = await run_in_threadpool(
        validate_url_and_fetch_pdf,
        url,
    )
    if not is_valid:
        return JSONResponse(status_code=400, content={"message": error_message})

    filename = PurePosixPath(unquote(urlparse(url).path)).name or "downloaded-paper.pdf"
    paper_upload_job = reserve_upload(
        db,
        requester=current_user,
        project_id=project_id,
        input_size_bytes=len(pdf_bytes),
        original_filename=filename,
        content_sha256=hashlib.sha256(pdf_bytes).hexdigest(),
    )
    try:
        await acquire_concurrency(
            user_id=int(current_user.id),
            category="background",
            operation_id=str(paper_upload_job.id),
        )
    except AILimitExceeded as exc:
        upload_reservation_repository.mark_as_failed(
            db=db,
            job_id=str(paper_upload_job.id),
            user=current_user,
            error_code=exc.code,
        )
        raise HTTPException(status_code=429, detail={"code": exc.code}) from None

    await upload_raw_file_microservice(
        file_contents=pdf_bytes,
        paper_upload_job=paper_upload_job,
        current_user=current_user,
        db=db,
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
    is_valid, error_message = await run_in_threadpool(
        validate_pdf_content,
        file_contents,
        "upload",
    )
    if not is_valid:
        return JSONResponse(status_code=400, content={"message": error_message})

    paper_upload_job = reserve_upload(
        db,
        requester=current_user,
        project_id=project_id,
        input_size_bytes=len(file_contents),
        original_filename=str(filename) if filename else None,
        content_sha256=hashlib.sha256(file_contents).hexdigest(),
    )
    try:
        await acquire_concurrency(
            user_id=int(current_user.id),
            category="background",
            operation_id=str(paper_upload_job.id),
        )
    except AILimitExceeded as exc:
        upload_reservation_repository.mark_as_failed(
            db=db,
            job_id=str(paper_upload_job.id),
            user=current_user,
            error_code=exc.code,
        )
        raise HTTPException(status_code=429, detail={"code": exc.code}) from None

    await upload_raw_file_microservice(
        file_contents=file_contents,
        paper_upload_job=paper_upload_job,
        current_user=current_user,
        db=db,
    )

    return JSONResponse(
        status_code=202,
        content={
            "message": "File upload started",
            "job_id": str(paper_upload_job.id),
        },
    )


async def upload_raw_file_microservice(
    file_contents: bytes,
    paper_upload_job: UploadReservation,
    current_user: CurrentUser,
    db: Session,
) -> str:
    """
    Helper function to upload a raw file using the microservice.
    """

    try:
        # Submit to microservice
        task_id = await submit_reserved_document(
            pdf_bytes=file_contents,
            upload_job=paper_upload_job,
            db=db,
            user=current_user,
        )
        # A content-addressed duplicate may complete immediately or attach to an
        # already-running canonical parse. This request did not create a worker
        # operation, so its concurrency lease must not wait for another job's
        # callback.
        if task_id.startswith("reused:") or task_id != str(paper_upload_job.id):
            await release_concurrency_by_id(
                user_id=int(current_user.id),
                category="background",
                operation_id=str(paper_upload_job.id),
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
        return task_id

    except Exception as exc:
        logger.error("Error submitting file to microservice", exc_info=True)
        upload_reservation_repository.mark_as_failed(
            db=db,
            job_id=str(paper_upload_job.id),
            user=current_user,
            error_code="jobs_submission_failed",
        )
        await release_concurrency_by_id(
            user_id=int(current_user.id),
            category="background",
            operation_id=str(paper_upload_job.id),
        )
        raise AppError(
            code="jobs_submission_failed",
            message="The document processing job could not be started",
            status_code=503,
        ) from exc
