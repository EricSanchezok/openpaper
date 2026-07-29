from __future__ import annotations

import uuid

from app.transport.http.public_v1.auth_dependencies import get_required_user
from app.database.database import get_db
from app.database.models import LibraryPaper
from app.errors import AppError
from app.helpers.s3 import DEFAULT_SIGNED_URL_TTL_SECONDS, s3_service
from app.policies.documents import require_document_access
from app.repositories.documents import document_repository
from app.modules.papers.application.contracts.documents import (
    DocumentFileUrlResponse,
    DocumentResponse,
    CollectPublicPaperResponse,
    LibraryPaperListResponse,
    LibraryPaperResponse,
    LibraryPaperShareResponse,
    LibraryPaperUpdateRequest,
    PublicPaperOwnerResponse,
    PublicPaperResponse,
)
from app.shared.application import Actor
from app.services.resource_quotas import require_library_document_capacity
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

document_router = APIRouter()
library_router = APIRouter()
public_document_router = APIRouter()


def _document_response(document: object) -> DocumentResponse:
    from app.database.models import Document

    if not isinstance(document, Document):
        raise TypeError("document_response_requires_document")
    return DocumentResponse.model_validate(
        {
            "id": document.id,
            "original_filename": document.original_filename,
            "mime_type": document.mime_type,
            "size_bytes": document.size_bytes,
            "title": document.title,
            "authors": document.authors,
            "abstract": document.abstract,
            "institutions": document.institutions,
            "keywords": document.keywords,
            "doi": document.doi,
            "journal": document.journal,
            "publisher": document.publisher,
            "publish_date": document.publish_date,
            "summary": document.summary,
            "summary_citations": document.summary_citations,
            "starter_questions": document.starter_questions,
            "processing_status": document.processing_status,
            "parser_quality": document.parser_quality,
            "parser_warning_code": document.parser_warning_code,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }
    )


def _library_response(library_paper: object) -> LibraryPaperResponse:
    from app.database.models import LibraryPaper

    if not isinstance(library_paper, LibraryPaper):
        raise TypeError("library_response_requires_library_paper")
    return LibraryPaperResponse.model_validate(
        {
            "id": library_paper.id,
            "user_id": library_paper.user_id,
            "status": library_paper.status,
            "last_accessed_at": library_paper.last_accessed_at,
            "metadata_overrides": library_paper.metadata_overrides,
            "is_public": library_paper.is_public,
            "preview_url": (
                s3_service.generate_presigned_url(library_paper.document.preview_s3_key)
                if library_paper.document.preview_s3_key
                else None
            ),
            "tags": [
                {"id": tag.id, "name": tag.name, "color": tag.color}
                for tag in library_paper.tags
            ],
            "document": _document_response(library_paper.document),
            "created_at": library_paper.created_at,
            "updated_at": library_paper.updated_at,
        }
    )


@library_router.get("/papers", response_model=LibraryPaperListResponse)
def list_library_papers(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperListResponse:
    entries = document_repository.list_library(db, user_id=current_user.id)
    return LibraryPaperListResponse(
        items=[_library_response(entry) for entry in entries]
    )


@library_router.patch(
    "/papers/{library_paper_id}",
    response_model=LibraryPaperResponse,
)
def update_library_paper(
    library_paper_id: uuid.UUID,
    request: LibraryPaperUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperResponse:
    entry = document_repository.update_library_paper(
        db,
        library_paper_id=library_paper_id,
        user_id=current_user.id,
        request=request,
    )
    return _library_response(entry)


@library_router.get(
    "/papers/by-document/{document_id}",
    response_model=LibraryPaperResponse,
)
def get_library_paper_by_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperResponse:
    entry = document_repository.require_library_paper_by_document(
        db,
        document_id=document_id,
        user_id=current_user.id,
    )
    return _library_response(entry)


@library_router.post(
    "/papers/{library_paper_id}/share",
    response_model=LibraryPaperShareResponse,
)
def share_library_paper(
    library_paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperShareResponse:
    token = document_repository.rotate_public_share(
        db,
        library_paper_id=library_paper_id,
        user_id=current_user.id,
    )
    return LibraryPaperShareResponse(share_token=token, is_public=True)


@library_router.delete(
    "/papers/{library_paper_id}/share",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unshare_library_paper(
    library_paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    document_repository.revoke_public_share(
        db,
        library_paper_id=library_paper_id,
        user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@library_router.delete(
    "/papers/{library_paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_library_paper(
    library_paper_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    document_repository.delete_library_paper(
        db,
        library_paper_id=library_paper_id,
        user_id=current_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@document_router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DocumentResponse:
    access = require_document_access(
        db,
        document_id=document_id,
        user_id=current_user.id,
        project_id=project_id,
    )
    return _document_response(access.document)


@document_router.get(
    "/{document_id}/file-url",
    response_model=DocumentFileUrlResponse,
)
def get_document_file_url(
    document_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DocumentFileUrlResponse:
    access = require_document_access(
        db,
        document_id=document_id,
        user_id=current_user.id,
        project_id=project_id,
    )
    try:
        file_url = s3_service.generate_presigned_url(access.document.s3_object_key)
    except RuntimeError as exc:
        raise AppError(
            code="document_file_url_unavailable",
            message="The document file is temporarily unavailable",
            status_code=503,
        ) from exc
    return DocumentFileUrlResponse(
        file_url=file_url,
        expires_in_seconds=DEFAULT_SIGNED_URL_TTL_SECONDS,
    )


@public_document_router.get(
    "/papers/{share_token}",
    response_model=PublicPaperResponse,
)
def get_public_paper(
    share_token: str,
    db: Session = Depends(get_db),
) -> PublicPaperResponse:
    shared = document_repository.require_public_share(db, token=share_token)
    try:
        file_url = s3_service.generate_presigned_url(shared.document.s3_object_key)
    except RuntimeError as exc:
        raise AppError(
            code="document_file_url_unavailable",
            message="The document file is temporarily unavailable",
            status_code=503,
        ) from exc
    return PublicPaperResponse(
        document=_document_response(shared.document),
        file_url=file_url,
        owner=PublicPaperOwnerResponse(
            id=shared.owner.id,
            display_name=shared.owner.display_name or shared.owner.email,
        ),
    )


@public_document_router.post(
    "/papers/{share_token}/collect",
    response_model=CollectPublicPaperResponse,
)
def collect_public_paper(
    share_token: str,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CollectPublicPaperResponse:
    shared = document_repository.require_public_share(db, token=share_token)
    existing = db.scalar(
        select(LibraryPaper).where(
            LibraryPaper.user_id == current_user.id,
            LibraryPaper.document_id == shared.document.id,
        )
    )
    if existing is not None:
        return CollectPublicPaperResponse(
            document_id=shared.document.id,
            library_paper_id=existing.id,
            already_exists=True,
        )
    require_library_document_capacity(
        db,
        user=current_user,
        document=shared.document,
    )
    document_repository.attach_library(
        db,
        document_id=shared.document.id,
        user_id=current_user.id,
    )
    db.commit()
    entry = document_repository.require_library_paper_by_document(
        db,
        document_id=shared.document.id,
        user_id=current_user.id,
    )
    return CollectPublicPaperResponse(
        document_id=shared.document.id,
        library_paper_id=entry.id,
        already_exists=False,
    )
