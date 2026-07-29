"""HTTP adapter for the shared PDF-ingestion application capability."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.papers.domain import MAX_PDF_BYTES, MAX_PDF_SIZE_MB
from app.modules.papers.application.contracts.uploads import (
    UploadAcceptedResponse,
    UploadFromUrlRequest,
)
from app.shared.application import Actor, ApplicationExecutor
from app.shared.domain import AppError
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, File, Header, Request, UploadFile

logger = logging.getLogger(__name__)
document_upload_router = APIRouter()

IdempotencyHeader = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=1, max_length=200),
]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    project_id: UUID | None = None,
) -> UploadAcceptedResponse:
    return await executor.command_async(
        lambda capabilities: capabilities.paper_ingestion.from_url(
            actor=current_user,
            url=str(payload.url),
            source=capabilities.pdf_url_source,
            project_id=project_id,
            idempotency_key=idempotency_key,
            ip_address=_client_ip(request),
        )
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
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
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
            status_code=413,
        )
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise AppError(
            code="invalid_pdf_content_type",
            message="Uploaded file must use a PDF content type",
            status_code=400,
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
                    status_code=413,
                )
            chunks.append(chunk)
        content = b"".join(chunks)
    except (OSError, RuntimeError):
        logger.exception("Error reading uploaded file")
        raise AppError(
            code="upload_read_failed",
            message="The uploaded file could not be read",
            status_code=400,
        ) from None

    return await executor.command_async(
        lambda capabilities: capabilities.paper_ingestion.from_bytes(
            actor=current_user,
            content=content,
            filename=file.filename,
            project_id=project_id,
            idempotency_key=idempotency_key,
            ip_address=_client_ip(request),
        )
    )
