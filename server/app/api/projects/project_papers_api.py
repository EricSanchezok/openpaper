import logging
import uuid

from app.auth.dependencies import get_required_user
from app.database.crud.paper_upload_crud import paper_upload_job_crud
from app.database.crud.projects.project_paper_crud import (
    ProjectPaperCreate,
    project_paper_crud,
)
from app.database.database import get_db
from app.database.models import Document
from app.database.telemetry import track_event
from app.helpers.s3 import s3_service
from app.helpers.subscription_limits import (
    can_user_add_papers_to_project,
    can_user_upload_paper,
)
from app.schemas.orm_responses import serialize_project
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Create API router
project_papers_router = APIRouter()


class CollectPaperFromProjectRequest(BaseModel):
    source_project_id: str
    paper_id: str


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
    try:
        can_upload, error_message = can_user_upload_paper(db, current_user)
        if not can_upload:
            return JSONResponse(
                status_code=403,
                content={"message": error_message},
            )

        project_paper: Document | None = project_paper_crud.get_paper_by_project(
            db,
            paper_id=uuid.UUID(request.paper_id),
            project_id=uuid.UUID(request.source_project_id),
            user=current_user,
        )

        if not project_paper:
            raise HTTPException(
                status_code=404,
                detail="Paper not found in the specified project or user does not have access.",
            )

        collected_paper = project_paper_crud.add_project_paper_to_library(
            db,
            paper_id=str(project_paper.id),
            project_id=request.source_project_id,
            current_user=current_user,
        )

        if not collected_paper:
            raise HTTPException(
                status_code=500,
                detail="Failed to add paper to library.",
            )

        track_event(
            "paper_collected_from_project",
            user_id=str(current_user.id),
            properties={
                "source_project_id": request.source_project_id,
                "paper_id": request.paper_id,
            },
            db=db,
        )

        return JSONResponse(
            status_code=201,
            content={
                "message": "Paper added to your library",
                "paper_id": str(collected_paper.id),
            },
        )

    except Exception as e:
        logger.error(f"Error collecting paper from project: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to add paper to library"},
        )


class AddPaperToProjectRequest(BaseModel):
    paper_ids: list[str]


@project_papers_router.post("/{project_id}")
async def add_paper_to_project(
    project_id: str,
    request: AddPaperToProjectRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Add a paper to a project"""
    try:
        can_add, error_message = can_user_add_papers_to_project(
            db,
            current_user,
            project_id=uuid.UUID(project_id),
            paper_count=len(request.paper_ids),
        )
        if not can_add:
            return JSONResponse(
                status_code=403,
                content={"message": error_message},
            )

        for paper_id in request.paper_ids:
            project_paper = project_paper_crud.create(
                db,
                obj_in=ProjectPaperCreate(paper_id=uuid.UUID(paper_id)),
                user=current_user,
                project_id=uuid.UUID(project_id),
            )
            if not project_paper:
                logger.error(
                    f"Failed to add paper {paper_id} to project {project_id}. Check permissions or if the paper already exists in the project."
                )

        track_event(
            "papers_added_to_project",
            user_id=str(current_user.id),
            properties={"project_id": project_id, "n_papers": len(request.paper_ids)},
            db=db,
        )

        return JSONResponse(
            status_code=201,
            content={"message": "Papers added to project successfully"},
        )

    except Exception as e:
        logger.error(f"Error adding paper to project: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to add paper to project"},
        )


@project_papers_router.get("/{project_id}")
async def get_project_papers(
    project_id: str,
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
    try:
        papers = project_paper_crud.get_papers_metadata_by_project_id(
            db, project_id=uuid.UUID(project_id), user=current_user
        )
        library_document_ids = set(
            project_paper_crud.get_library_document_ids(
                db,
                document_ids=[paper.id for paper in papers],
                user=current_user,
            )
        )

        file_urls: dict[str, str | None] = {}
        if load_urls:
            # Bulk retrieve presigned URLs (optimized with parallelization)
            file_urls = s3_service.get_cached_presigned_urls_bulk(
                db=db,
                papers=papers,
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

    except Exception as e:
        logger.error(f"Error fetching project papers: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to fetch project papers"},
        )


@project_papers_router.get("/{project_id}/pending-jobs")
async def get_project_pending_jobs(
    project_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """
    Get upload jobs still in progress for a project.

    Lets the client rehydrate the upload tracker after a refresh, since the
    in-flight jobs are otherwise only held in browser state.
    """
    try:
        jobs = paper_upload_job_crud.get_in_progress_jobs_for_project(
            db, project_id=uuid.UUID(project_id), user=current_user
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

    except Exception as e:
        logger.error(f"Error fetching pending project jobs: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to fetch pending project jobs"},
        )


@project_papers_router.get("/{project_id}/{paper_id}/file-url")
async def get_project_paper_file_url(
    project_id: str,
    paper_id: str,
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
    try:
        paper = project_paper_crud.get_paper_by_project(
            db,
            paper_id=uuid.UUID(paper_id),
            project_id=uuid.UUID(project_id),
            user=current_user,
        )

        if not paper:
            raise HTTPException(
                status_code=404,
                detail="Paper not found in the specified project or user does not have access.",
            )

        file_url = s3_service.get_cached_presigned_url(
            db,
            paper_id=str(paper.id),
            object_key=str(paper.s3_object_key),
            current_user=current_user,
        )

        if not file_url:
            raise HTTPException(status_code=404, detail="File not found")

        return JSONResponse(
            status_code=200,
            content={"file_url": file_url},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching project paper file URL: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to fetch project paper file URL"},
        )


@project_papers_router.get("/from/{paper_id}")
async def get_projects_from_paper_id(
    paper_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Get all projects associated with a specific paper"""
    try:
        projects = project_paper_crud.get_projects_by_paper_id(
            db, paper_id=uuid.UUID(paper_id), user=current_user
        )

        return JSONResponse(
            status_code=200,
            content=[serialize_project(project) for project in projects],
        )

    except Exception as e:
        logger.error(f"Error fetching projects for paper: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to fetch projects for paper"},
        )


@project_papers_router.delete("/{project_id}/{project_paper_id}")
async def remove_paper_from_project(
    project_id: str,
    project_paper_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Remove a paper from a project"""
    try:
        # The id passed here is the id of the ProjectPaper association
        removed_project_paper = project_paper_crud.remove_by_paper_and_project(
            db,
            paper_id=uuid.UUID(project_paper_id),
            project_id=uuid.UUID(project_id),
            user=current_user,
        )

        if not removed_project_paper:
            raise HTTPException(
                status_code=404,
                detail="Project paper association not found or user does not have permission to delete.",
            )

        track_event("paper_removed_from_project", user_id=str(current_user.id), db=db)

        return JSONResponse(
            status_code=200,
            content={"message": "Paper removed from project successfully"},
        )
    except Exception as e:
        logger.error(f"Error removing paper from project: {e}", exc_info=True)
        return JSONResponse(
            status_code=400,
            content={"message": "Failed to remove paper from project"},
        )
