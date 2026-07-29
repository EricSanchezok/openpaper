"""HTTP adapters for Papers, Library entries, and public shares."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.container import (
    build_paper_content,
    build_citation_resolver,
    build_paper_details,
    build_paper_download,
    build_paper_library,
)
from app.modules.papers.application.contracts.citation import CitationResult
from app.database.database import get_db
from app.modules.papers.application.contracts.documents import (
    CollectPublicPaperResponse,
    DocumentContentResponse,
    DocumentFileUrlResponse,
    DocumentResponse,
    LibraryPaperListResponse,
    LibraryPaperResponse,
    LibraryPaperShareResponse,
    LibraryPaperUpdateRequest,
    PublicPaperResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

document_router = APIRouter()
library_router = APIRouter()
public_document_router = APIRouter()


@library_router.get("/papers", response_model=LibraryPaperListResponse)
def list_library_papers(
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperListResponse:
    return build_paper_library(db=db).list(actor=current_user)


@library_router.patch(
    "/papers/{document_id}",
    response_model=LibraryPaperResponse,
)
def update_library_paper(
    document_id: UUID,
    request: LibraryPaperUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperResponse:
    return build_paper_library(db=db).update(
        actor=current_user,
        document_id=document_id,
        request=request,
    )


@library_router.get(
    "/papers/{document_id}",
    response_model=LibraryPaperResponse,
)
def get_library_paper_by_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperResponse:
    return build_paper_library(db=db).get(
        actor=current_user,
        document_id=document_id,
    )


@library_router.post(
    "/papers/{document_id}/share",
    response_model=LibraryPaperShareResponse,
    status_code=status.HTTP_201_CREATED,
)
def share_library_paper(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperShareResponse:
    return build_paper_library(db=db).share(
        actor=current_user,
        document_id=document_id,
    )


@library_router.delete(
    "/papers/{document_id}/share",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unshare_library_paper(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_paper_library(db=db).unshare(
        actor=current_user,
        document_id=document_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@library_router.delete(
    "/papers/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_library_paper(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_paper_library(db=db).remove(
        actor=current_user,
        document_id=document_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@document_router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    project_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DocumentResponse:
    return build_paper_details(db=db)(
        actor=current_user,
        document_id=document_id,
        project_id=project_id,
    )


@document_router.get(
    "/{document_id}/content",
    response_model=DocumentContentResponse,
)
def get_document_content(
    document_id: UUID,
    project_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DocumentContentResponse:
    paper = build_paper_content(db=db).read(
        actor=current_user,
        document_id=document_id,
        project_id=project_id,
    )
    return DocumentContentResponse(
        document_id=paper.document_id,
        title=paper.title,
        abstract=paper.abstract,
        content=paper.raw_content,
    )


@document_router.get(
    "/{document_id}/download-url",
    response_model=DocumentFileUrlResponse,
)
def get_document_file_url(
    document_id: UUID,
    project_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> DocumentFileUrlResponse:
    return build_paper_download(db=db)(
        actor=current_user,
        document_id=document_id,
        project_id=project_id,
    )


@document_router.get(
    "/{document_id}/citation",
    response_model=CitationResult,
)
def get_document_citation(
    document_id: UUID,
    style: str = "APA",
    project_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CitationResult:
    return build_citation_resolver(db=db)(
        actor=current_user,
        document_id=document_id,
        style=style,
        project_id=project_id,
    )


@public_document_router.get(
    "/{share_token}",
    response_model=PublicPaperResponse,
)
def get_public_paper(
    share_token: str,
    db: Session = Depends(get_db),
) -> PublicPaperResponse:
    return build_paper_library(db=db).get_public(share_token=share_token)


@public_document_router.post(
    "/{share_token}/collect",
    response_model=CollectPublicPaperResponse,
    status_code=status.HTTP_201_CREATED,
)
def collect_public_paper(
    share_token: str,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> CollectPublicPaperResponse:
    return build_paper_library(db=db).collect_public(
        actor=current_user,
        share_token=share_token,
    )
