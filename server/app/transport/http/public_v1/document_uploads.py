"""HTTP adapter for the shared PDF-ingestion application capability."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from app.bootstrap.execution import get_paper_ingestion_workflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.modules.papers.domain import MAX_PDF_BYTES, MAX_PDF_SIZE_MB
from app.modules.papers.application.contracts.uploads import (
    UploadAcceptedResponse,
    UploadFromUrlRequest,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.transport.client_ip import http_client_ip
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, File, Header, Request, UploadFile

logger = logging.getLogger(__name__)
document_upload_router = APIRouter()

IdempotencyHeader = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=1, max_length=200),
]


@document_upload_router.post(
    "/urls",
    response_model=UploadAcceptedResponse,
    status_code=202,
)
async def upload_pdf_from_url(
    payload: UploadFromUrlRequest,
    request: Request,
    idempotency_key: IdempotencyHeader = None,
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    ingestion: PaperIngestionWorkflow = Depends(get_paper_ingestion_workflow),
    project_id: UUID | None = None,
) -> UploadAcceptedResponse:
    return await ingestion.from_url(
        actor=current_user,
        operation=operation,
        url=str(payload.url),
        project_id=project_id,
        idempotency_key=idempotency_key,
        ip_address=http_client_ip(request),
    )


@document_upload_router.post(
    "/uploads",
    response_model=UploadAcceptedResponse,
    status_code=202,
)
async def upload_pdf(
    request: Request,
    file: UploadFile = File(...),
    idempotency_key: IdempotencyHeader = None,
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    ingestion: PaperIngestionWorkflow = Depends(get_paper_ingestion_workflow),
    project_id: UUID | None = None,
) -> UploadAcceptedResponse:
    max_bytes = MAX_PDF_BYTES
    declared_size = request.headers.get("content-length")
    if declared_size and (
        not declared_size.isdigit() or int(declared_size) > max_bytes + 1024 * 1024
    ):
        raise AppError(
            code="upload_too_large",
            message=f"File too large (max {MAX_PDF_SIZE_MB}MB)",
            kind=FailureKind.PAYLOAD_TOO_LARGE,
        )
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise AppError(
            code="invalid_pdf_content_type",
            message="Uploaded file must use a PDF content type",
            kind=FailureKind.INVALID_ARGUMENT,
        )

    try:
        chunks: list[bytes] = []
        total = 0
        while chunk := await file.read(65_536):
            total += len(chunk)
            if total > max_bytes:
                raise AppError(
                    code="upload_too_large",
                    message=f"File too large (max {MAX_PDF_SIZE_MB}MB)",
                    kind=FailureKind.PAYLOAD_TOO_LARGE,
                )
            chunks.append(chunk)
        content = b"".join(chunks)
    except (OSError, RuntimeError):
        logger.exception("paper_upload.read_failed")
        raise AppError(
            code="upload_read_failed",
            message="The uploaded file could not be read",
            kind=FailureKind.INVALID_ARGUMENT,
        ) from None

    return await ingestion.from_bytes(
        actor=current_user,
        operation=operation,
        content=content,
        filename=file.filename,
        project_id=project_id,
        idempotency_key=idempotency_key,
        ip_address=http_client_ip(request),
    )
