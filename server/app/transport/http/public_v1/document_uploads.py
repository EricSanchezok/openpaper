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

from starlette.concurrency import run_in_threadpool

import logging
import hashlib
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse
from uuid import UUID

from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.modules.papers.infrastructure.upload_repository import (
    upload_reservation_repository,
)
from app.database.database import get_db
from app.shared.domain import AppError
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
)
from app.helpers.parser import (
    MAX_UPLOAD_SIZE_MB,
    validate_pdf_content,
    validate_url_and_fetch_pdf,
)
from app.shared.application import Actor
from app.modules.papers.application.contracts.uploads import (
    UploadAcceptedResponse,
    UploadFromUrlRequest,
)
from app.modules.papers.infrastructure.submission import dispatch_reserved_document
from app.modules.papers.infrastructure.upload_reservations import reserve_upload
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    File,
    Request,
    UploadFile,
)
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

# Create API router with prefix
document_upload_router = APIRouter()


@document_upload_router.post(
    "/urls",
    response_model=UploadAcceptedResponse,
    status_code=202,
)
async def upload_pdf_from_url(
    request: UploadFromUrlRequest,
    http_request: Request,
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
    project_id: UUID | None = None,
) -> UploadAcceptedResponse:
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
        raise AppError(
            code=exc.code,
            message="Upload rate limit exceeded",
            status_code=429,
        ) from None

    # Validate the URL and fetch PDF content
    url = str(request.url)
    is_valid, pdf_bytes, error_message = await run_in_threadpool(
        validate_url_and_fetch_pdf,
        url,
    )
    if not is_valid:
        raise AppError(
            code="invalid_pdf_url",
            message=error_message or "The URL did not return a valid PDF",
            status_code=400,
        )

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
        raise AppError(
            code=exc.code,
            message="Too many background jobs are already running",
            status_code=429,
        ) from None

    await dispatch_reserved_document(
        pdf_bytes=pdf_bytes,
        upload_job=paper_upload_job,
        user=current_user,
        db=db,
    )
    return UploadAcceptedResponse(job_id=paper_upload_job.id)


@document_upload_router.post(
    "/uploads",
    response_model=UploadAcceptedResponse,
    status_code=202,
)
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    current_user: Actor = Depends(get_required_user),
    db: Session = Depends(get_db),
    project_id: UUID | None = None,
) -> UploadAcceptedResponse:
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
        raise AppError(
            code=exc.code,
            message="Upload rate limit exceeded",
            status_code=429,
        ) from None
    max_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    declared_size = request.headers.get("content-length")
    if declared_size and (
        not declared_size.isdigit() or int(declared_size) > max_bytes + 1024 * 1024
    ):
        raise AppError(
            code="upload_too_large",
            message=f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)",
            status_code=413,
        )
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise AppError(
            code="invalid_pdf_content_type",
            message="Uploaded file must use a PDF content type",
            status_code=400,
        )

    # Starlette spools multipart files, but an explicit running cap prevents an
    # unbounded application-level read when Content-Length is absent or false.
    try:
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(65536):
            total += len(chunk)
            if total > max_bytes:
                raise AppError(
                    code="upload_too_large",
                    message=f"File too large (max {MAX_UPLOAD_SIZE_MB}MB)",
                    status_code=413,
                )
            chunks.append(chunk)
        file_contents = b"".join(chunks)
        filename = file.filename
    except (OSError, RuntimeError):
        logger.exception("Error reading uploaded file")
        raise AppError(
            code="upload_read_failed",
            message="The uploaded file could not be read",
            status_code=400,
        )

    # Validate PDF content
    is_valid, error_message = await run_in_threadpool(
        validate_pdf_content,
        file_contents,
        "upload",
    )
    if not is_valid:
        raise AppError(
            code="invalid_pdf",
            message=error_message or "The uploaded file is not a valid PDF",
            status_code=400,
        )

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
        raise AppError(
            code=exc.code,
            message="Too many background jobs are already running",
            status_code=429,
        ) from None

    await dispatch_reserved_document(
        pdf_bytes=file_contents,
        upload_job=paper_upload_job,
        user=current_user,
        db=db,
    )
    return UploadAcceptedResponse(job_id=paper_upload_job.id)
