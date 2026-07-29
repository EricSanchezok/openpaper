"""HTTP adapter for documents held by Projects."""

from uuid import UUID

from app.bootstrap.container import build_projects
from app.database.database import get_db
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectListResponse,
    ProjectPaperCollectedResponse,
    ProjectPaperFileUrlResponse,
    ProjectPaperListResponse,
    ProjectPapersAddedResponse,
    ProjectPendingUploadsResponse,
)
from app.shared.application import Actor
from app.transport.http.public_v1.auth_dependencies import get_required_user
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

project_papers_router = APIRouter()
paper_projects_router = APIRouter()
library_project_papers_router = APIRouter()


@library_project_papers_router.post(
    "/papers",
    response_model=ProjectPaperCollectedResponse,
    status_code=status.HTTP_201_CREATED,
)
def collect_paper_from_project(
    request: CollectPaperFromProjectRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPaperCollectedResponse:
    return build_projects(db=db).collect_document(
        actor=current_user,
        request=request,
    )


@project_papers_router.post(
    "/{project_id}/papers",
    response_model=ProjectPapersAddedResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_paper_to_project(
    project_id: UUID,
    request: AddPaperToProjectRequest,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPapersAddedResponse:
    return build_projects(db=db).add_documents(
        actor=current_user,
        project_id=project_id,
        request=request,
    )


@project_papers_router.get(
    "/{project_id}/papers",
    response_model=ProjectPaperListResponse,
)
def get_project_papers(
    project_id: UUID,
    load_urls: bool = False,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPaperListResponse:
    return build_projects(db=db).documents(
        actor=current_user,
        project_id=project_id,
        load_urls=load_urls,
    )


@project_papers_router.get(
    "/{project_id}/papers/pending-jobs",
    response_model=ProjectPendingUploadsResponse,
)
def get_project_pending_jobs(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPendingUploadsResponse:
    return build_projects(db=db).pending_uploads(
        actor=current_user,
        project_id=project_id,
    )


@project_papers_router.get(
    "/{project_id}/papers/{document_id}/download-url",
    response_model=ProjectPaperFileUrlResponse,
)
def get_project_paper_file_url(
    project_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPaperFileUrlResponse:
    return build_projects(db=db).document_download(
        actor=current_user,
        project_id=project_id,
        document_id=document_id,
    )


@paper_projects_router.get(
    "/{document_id}/projects",
    response_model=ProjectListResponse,
)
def get_projects_from_document_id(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> ProjectListResponse:
    return build_projects(db=db).projects_for_document(
        actor=current_user,
        document_id=document_id,
    )


@project_papers_router.delete(
    "/{project_id}/papers/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_paper_from_project(
    project_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: Actor = Depends(get_required_user),
) -> Response:
    build_projects(db=db).remove_document(
        actor=current_user,
        project_id=project_id,
        document_id=document_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
