from uuid import UUID

from app.auth.dependencies import get_required_user
from app.repositories.upload_reservations import upload_reservation_repository
from app.repositories.project_documents import project_document_repository
from app.database.database import get_db
from app.database.telemetry import track_event
from app.errors import AppError
from app.helpers.s3 import s3_service
from app.schemas.projects import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectPaperCollectedResponse,
    ProjectPaperFileUrlResponse,
    ProjectPaperListResponse,
    ProjectPaperSummaryResponse,
    ProjectPapersAddedResponse,
    ProjectPendingUploadResponse,
    ProjectPendingUploadsResponse,
    ProjectResponse,
)
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from .responses import project_response

project_papers_router = APIRouter()


@project_papers_router.post(
    "/papers/collect",
    response_model=ProjectPaperCollectedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def collect_paper_from_project(
    request: CollectPaperFromProjectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectPaperCollectedResponse:
    """
    Add a project document to the current user's personal library without
    copying its S3 object or parsed content.
    """
    collected_document = project_document_repository.add_project_paper_to_library(
        db,
        document_id=request.paper_id,
        project_id=request.source_project_id,
        current_user=current_user,
    )
    if collected_document is None:
        raise AppError(
            code="project_document_not_found",
            message="Document not found in this Project",
            status_code=404,
        )

    track_event(
        "paper_collected_from_project",
        user_id=str(current_user.id),
        properties={
            "source_project_id": str(request.source_project_id),
            "paper_id": str(request.paper_id),
        },
        db=db,
    )
    return ProjectPaperCollectedResponse(paper_id=collected_document.id)


@project_papers_router.post(
    "/{project_id}/papers",
    response_model=ProjectPapersAddedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_paper_to_project(
    project_id: UUID,
    request: AddPaperToProjectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectPapersAddedResponse:
    associations, existing_count = project_document_repository.attach_library_documents(
        db,
        document_ids=request.paper_ids,
        user=current_user,
        project_id=project_id,
    )
    track_event(
        "papers_added_to_project",
        user_id=str(current_user.id),
        properties={
            "project_id": str(project_id),
            "added_count": len(associations),
            "existing_count": existing_count,
        },
        db=db,
    )
    return ProjectPapersAddedResponse(
        added_count=len(associations),
        existing_count=existing_count,
    )


@project_papers_router.get(
    "/{project_id}/papers",
    response_model=ProjectPaperListResponse,
)
async def get_project_papers(
    project_id: UUID,
    load_urls: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectPaperListResponse:
    """
    Get all papers for a specific project.

    Presigned file URLs are only generated when ``load_urls=true``. Most
    callers (e.g. the project overview page) just need paper metadata, and
    generating URLs for every paper is expensive on cache expiry. Callers
    that need a URL for a single paper should use the
    ``/{project_id}/{paper_id}/file-url`` endpoint instead.
    """
    papers = project_document_repository.get_papers_metadata_by_project_id(
        db, project_id=project_id, user=current_user
    )
    library_document_ids = set(
        project_document_repository.get_library_document_ids(
            db,
            document_ids=[paper.id for paper in papers],
            user=current_user,
        )
    )

    file_urls: dict[str, str] = {}
    if load_urls:
        file_urls = s3_service.generate_presigned_urls(
            {str(paper.id): paper.s3_object_key for paper in papers}
        )

    return ProjectPaperListResponse(
        papers=[
            ProjectPaperSummaryResponse(
                id=paper.id,
                title=paper.title,
                created_at=paper.created_at,
                abstract=paper.abstract,
                authors=paper.authors,
                institutions=paper.institutions,
                status="reading",
                journal=paper.journal,
                publisher=paper.publisher,
                doi=paper.doi,
                publish_date=paper.publish_date,
                file_url=file_urls.get(str(paper.id)),
                in_library=paper.id in library_document_ids,
            )
            for paper in papers
        ]
    )


@project_papers_router.get(
    "/{project_id}/papers/pending-jobs",
    response_model=ProjectPendingUploadsResponse,
)
async def get_project_pending_jobs(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectPendingUploadsResponse:
    """
    Get upload jobs still in progress for a project.

    Lets the client rehydrate the upload tracker after a refresh, since the
    in-flight jobs are otherwise only held in browser state.
    """
    jobs = upload_reservation_repository.get_in_progress_jobs_for_project(
        db, project_id=project_id, user=current_user
    )
    return ProjectPendingUploadsResponse(
        jobs=[
            ProjectPendingUploadResponse(
                job_id=job.id,
                status=job.job.status,
                paper_id=paper.id,
                title=paper.title,
                started_at=job.job.started_at,
            )
            for job, paper in jobs
        ]
    )


@project_papers_router.get(
    "/{project_id}/papers/{paper_id}/file-url",
    response_model=ProjectPaperFileUrlResponse,
)
async def get_project_paper_file_url(
    project_id: UUID,
    paper_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectPaperFileUrlResponse:
    """
    Get a presigned file URL for a single paper within a project.

    Access is granted via project membership rather than paper ownership, so
    collaborators can open papers they don't own. This is the cheap path for
    "my URL expired, give me a fresh one" — callers should use this instead
    of refetching the whole project paper list.
    """
    paper = project_document_repository.get_paper_by_project(
        db,
        paper_id=paper_id,
        project_id=project_id,
        user=current_user,
    )
    if paper is None:
        raise AppError(
            code="project_document_not_found",
            message="Document not found in this Project",
            status_code=404,
        )

    file_url = s3_service.generate_presigned_url(paper.s3_object_key)

    return ProjectPaperFileUrlResponse(file_url=file_url)


@project_papers_router.get(
    "/papers/from/{paper_id}",
    response_model=list[ProjectResponse],
)
async def get_projects_from_paper_id(
    paper_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> list[ProjectResponse]:
    """Get all projects associated with a specific paper"""
    projects = project_document_repository.get_projects_by_paper_id(
        db, paper_id=paper_id, user=current_user
    )
    return [
        project_response(db, project=project, current_user_id=current_user.id)
        for project in projects
    ]


@project_papers_router.delete(
    "/{project_id}/papers/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_paper_from_project(
    project_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> Response:
    """Remove a paper from a project"""
    project_document_repository.remove_by_paper_and_project(
        db,
        paper_id=document_id,
        project_id=project_id,
        user=current_user,
    )
    track_event("paper_removed_from_project", user_id=str(current_user.id), db=db)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
