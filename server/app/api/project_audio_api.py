from app.api.types import ApiResponse
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.api.paper_audio_api import AudioOverviewCreateRequest
from app.auth.dependencies import get_required_user
from app.database.crud.audio_overview_crud import (
    AudioOverviewJobCreate,
    audio_overview_crud,
    audio_overview_job_crud,
)
from app.database.crud.projects.project_crud import project_crud
from app.database.database import get_db
from app.database.models import ConversableType, JobStatus, ProjectRoles
from app.database.telemetry import track_event
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency,
)
from app.helpers.s3 import s3_service
from app.llm.token_credits import has_token_credits
from app.schemas.user import CurrentUser
from app.tasks.audio_overview import generate_audio_overview_async
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

# Create API router with prefix
project_audio_router = APIRouter()


@project_audio_router.post("/{project_id}")
async def create_project_audio_overview(
    request: Request,
    project_id: str,
    audio_request: AudioOverviewCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Create audio overview for a project by ID
    """
    if not has_token_credits(db, user=current_user):
        return JSONResponse(
            status_code=429,
            content={"code": "token_quota_exceeded"},
        )
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=request.client.host if request.client else "unknown",
            feature="audio",
        )
    except AILimitExceeded as exc:
        return JSONResponse(status_code=429, content={"code": exc.code})

    project = project_crud.get(db, id=project_id, user=current_user)

    if not project:
        return JSONResponse(status_code=404, content={"message": "Project not found"})

    has_edit_permission = project_crud.has_role(
        db, project_id=project_id, user_id=current_user.id, role=ProjectRoles.ADMIN
    ) or project_crud.has_role(
        db,
        project_id=project_id,
        user_id=current_user.id,
        role=ProjectRoles.EDITOR,
    )

    if not has_edit_permission:
        return JSONResponse(
            status_code=403,
            content={
                "message": "You do not have permission to create audio overviews for this project"
            },
        )

    project_uuid = uuid.UUID(str(project.id))

    # Create the audio overview job
    audio_overview_job = audio_overview_job_crud.create(
        db,
        obj_in=AudioOverviewJobCreate(
            conversable_id=project_uuid, conversable_type=ConversableType.PROJECT
        ),
        user=current_user,
    )

    if not audio_overview_job:
        return JSONResponse(
            status_code=500,
            content={"message": "Failed to create audio overview job"},
        )

    job_id_as_uuid = uuid.UUID(str(audio_overview_job.id))
    logger.info(f"Created audio overview job with ID: {job_id_as_uuid}")
    try:
        background_lease = await acquire_concurrency(
            user_id=int(current_user.id),
            category="background",
            operation_id=str(job_id_as_uuid),
        )
        try:
            await acquire_concurrency(
                user_id=int(current_user.id),
                category="audio",
                operation_id=str(job_id_as_uuid),
            )
        except Exception:
            await release_concurrency(background_lease)
            raise
    except AILimitExceeded as exc:
        audio_overview_job_crud.update_status(
            db,
            job_id=job_id_as_uuid,
            status=JobStatus.FAILED,
            current_user=current_user,
            status_message=exc.code,
        )
        return JSONResponse(status_code=429, content={"code": exc.code})

    # Add the audio generation task as a background task
    background_tasks.add_task(
        generate_audio_overview_async,
        project_id=project_uuid,
        user=current_user,
        audio_overview_job_id=job_id_as_uuid,
        additional_instructions=audio_request.additional_instructions,
        length=audio_request.length,
    )

    track_event(
        "audio_overview_requested",
        properties={
            "job_id": str(job_id_as_uuid),
            "conversable_type": "project",
        },
        user_id=str(current_user.id),
        db=db,
    )

    # Return the job ID immediately so the client can track progress
    return JSONResponse(
        status_code=202,
        content={
            "message": "Audio overview generation started",
            "job_id": str(job_id_as_uuid),
            "status": audio_overview_job.status,
        },
    )


@project_audio_router.get("/{id}")
async def get_project_audio_overviews(
    request: Request,
    id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get all audio overviews for a specific project by ID
    """
    # Fetch the audio overviews from the database
    audio_overviews = audio_overview_crud.get_by_conversable_and_user(
        db,
        conversable_id=uuid.UUID(id),
        conversable_type=ConversableType.PROJECT,
        current_user=current_user,
    )

    if not audio_overviews:
        # If no audio overviews are found, return an empty list
        return JSONResponse(status_code=200, content=[])

    # Convert the audio overviews to a list of dictionaries
    audio_overview_list = [
        audio_overview_crud.overview_to_dict(overview) for overview in audio_overviews
    ]

    return JSONResponse(
        status_code=200,
        content=audio_overview_list,
    )


@project_audio_router.get("/jobs/{project_id}")
async def get_audio_overview_jobs_by_project_id(
    request: Request,
    project_id: str,
    all: bool = False,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get all audio overview jobs for a specific project by ID
    """
    # Fetch the audio overview jobs from the database
    audio_overview_jobs = audio_overview_job_crud.get_by_conversable_and_user(
        db,
        conversable_id=uuid.UUID(project_id),
        conversable_type=ConversableType.PROJECT,
        current_user=current_user,
    )

    if not audio_overview_jobs:
        # If no audio overview jobs are found, return an empty list
        return JSONResponse(status_code=200, content=[])

    if not all:
        # Use UTC for comparison
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        audio_overview_jobs = [
            job
            for job in audio_overview_jobs
            if (
                job.status != JobStatus.COMPLETED
                and job.started_at is not None
                and job.started_at >= one_hour_ago
            )
        ]

    # Convert the audio overview jobs to a list of dictionaries
    audio_overview_job_list = [
        audio_overview_job_crud.job_to_dict(job) for job in audio_overview_jobs
    ]

    return JSONResponse(
        status_code=200,
        content=audio_overview_job_list,
    )


@project_audio_router.get("/file/{project_id}/{audio_overview_id}")
async def get_audio_overview_by_id(
    request: Request,
    project_id: str,
    audio_overview_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get a specific audio overview by ID
    """
    # Fetch the audio overview from the database
    audio_overview = audio_overview_crud.get_by_id_project_and_user(
        db,
        id=uuid.UUID(audio_overview_id),
        project_id=uuid.UUID(project_id),
        current_user=current_user,
    )

    if not audio_overview:
        return JSONResponse(
            status_code=404, content={"message": "Audio overview not found"}
        )

    # Generate a presigned URL for the audio file
    signed_url = s3_service.generate_presigned_url(
        object_key=str(audio_overview.s3_object_key),
    )

    if not signed_url:
        return JSONResponse(status_code=404, content={"message": "File not found"})

    # Convert the audio overview to a dictionary
    audio_overview_dict = audio_overview_crud.overview_to_dict(audio_overview)

    audio_overview_dict["audio_url"] = signed_url

    return JSONResponse(
        status_code=200,
        content=audio_overview_dict,
    )
