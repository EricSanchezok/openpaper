from uuid import UUID

from app.auth.dependencies import get_required_user
from app.database.crud.paper_upload_crud import paper_upload_job_crud
from app.database.crud.projects.project_paper_crud import project_paper_crud
from app.database.database import get_db
from app.database.telemetry import track_event
from app.errors import AppError
from app.helpers.s3 import s3_service
from app.schemas.orm_responses import serialize_project
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

project_papers_router = APIRouter()


class CollectPaperFromProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_project_id: UUID
    paper_id: UUID


@project_papers_router.post("/collect")
async def collect_paper_from_project(
    request: CollectPaperFromProjectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Add a project document to the current user's personal library without
    copying its S3 object or parsed content.
    """
    collected_document = project_paper_crud.add_project_paper_to_library(
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
    return JSONResponse(
        status_code=201,
        content={
            "message": "Paper added to your library",
            "paper_id": str(collected_document.id),
        },
    )


class AddPaperToProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_ids: list[UUID] = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> "AddPaperToProjectRequest":
        if len(set(self.paper_ids)) != len(self.paper_ids):
            raise ValueError("paper_ids must be unique")
        return self


@project_papers_router.post("/{project_id}")
async def add_paper_to_project(
    project_id: UUID,
    request: AddPaperToProjectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    associations, existing_count = project_paper_crud.attach_library_documents(
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
    return JSONResponse(
        status_code=201,
        content={
            "message": "Papers added to project successfully",
            "added_count": len(associations),
            "existing_count": existing_count,
        },
    )


@project_papers_router.get("/{project_id}")
async def get_project_papers(
    project_id: UUID,
    load_urls: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get all papers for a specific project.

    Presigned file URLs are only generated when ``load_urls=true``. Most
    callers (e.g. the project overview page) just need paper metadata, and
    generating URLs for every paper is expensive on cache expiry. Callers
    that need a URL for a single paper should use the
    ``/{project_id}/{paper_id}/file-url`` endpoint instead.
    """
    papers = project_paper_crud.get_papers_metadata_by_project_id(
        db, project_id=project_id, user=current_user
    )
    library_document_ids = set(
        project_paper_crud.get_library_document_ids(
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

    return JSONResponse(
        status_code=200,
        content={
            "papers": [
                {
                    "id": str(paper.id),
                    "title": paper.title,
                    "created_at": str(paper.created_at),
                    "abstract": paper.abstract,
                    "authors": paper.authors,
                    "institutions": paper.institutions,
                    "status": "reading",
                    "journal": paper.journal,
                    "publisher": paper.publisher,
                    "doi": paper.doi,
                    "publish_date": (
                        str(paper.publish_date) if paper.publish_date else None
                    ),
                    "file_url": file_urls.get(str(paper.id)),
                    "in_library": paper.id in library_document_ids,
                }
                for paper in papers
            ]
        },
    )


@project_papers_router.get("/{project_id}/pending-jobs")
async def get_project_pending_jobs(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get upload jobs still in progress for a project.

    Lets the client rehydrate the upload tracker after a refresh, since the
    in-flight jobs are otherwise only held in browser state.
    """
    jobs = paper_upload_job_crud.get_in_progress_jobs_for_project(
        db, project_id=project_id, user=current_user
    )
    return JSONResponse(
        status_code=200,
        content={
            "jobs": [
                {
                    "job_id": str(job.id),
                    "status": job.status,
                    "paper_id": str(paper.id),
                    "title": paper.title,
                    "started_at": (
                        job.started_at.isoformat() if job.started_at else None
                    ),
                }
                for job, paper in jobs
            ]
        },
    )


@project_papers_router.get("/{project_id}/{paper_id}/file-url")
async def get_project_paper_file_url(
    project_id: UUID,
    paper_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get a presigned file URL for a single paper within a project.

    Access is granted via project membership rather than paper ownership, so
    collaborators can open papers they don't own. This is the cheap path for
    "my URL expired, give me a fresh one" — callers should use this instead
    of refetching the whole project paper list.
    """
    paper = project_paper_crud.get_paper_by_project(
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

    return JSONResponse(status_code=200, content={"file_url": file_url})


@project_papers_router.get("/from/{paper_id}")
async def get_projects_from_paper_id(
    paper_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Get all projects associated with a specific paper"""
    projects = project_paper_crud.get_projects_by_paper_id(
        db, paper_id=paper_id, user=current_user
    )
    return JSONResponse(
        status_code=200,
        content=[serialize_project(project) for project in projects],
    )


@project_papers_router.delete("/{project_id}/{document_id}")
async def remove_paper_from_project(
    project_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Remove a paper from a project"""
    project_paper_crud.remove_by_paper_and_project(
        db,
        paper_id=document_id,
        project_id=project_id,
        user=current_user,
    )
    track_event("paper_removed_from_project", user_id=str(current_user.id), db=db)
    return JSONResponse(
        status_code=200,
        content={"message": "Paper removed from project successfully"},
    )
