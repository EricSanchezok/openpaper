from uuid import UUID

from app.auth.dependencies import get_required_user
from app.database.crud.artifact_crud import artifact_crud
from app.database.database import get_db
from app.database.models import ArtifactKind
from app.policies.projects import require_project_access
from app.schemas.projects import (
    ProjectArtifactListResponse,
    ProjectArtifactResponse,
    ProjectCitationArtifactPayload,
)
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

project_artifacts_router = APIRouter()


@project_artifacts_router.get(
    "/{project_id}",
    response_model=ProjectArtifactListResponse,
)
async def get_project_artifacts(
    project_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ProjectArtifactListResponse:
    """
    Get chat-generated artifacts (citations) for a project.

    Project conversations remain private. Only the explicitly shared artifact
    payload is visible to collaborators.
    """
    require_project_access(db, project_id=project_id, user_id=current_user.id)

    rows = artifact_crud.list_for_project(
        db,
        project_id=project_id,
        kind=ArtifactKind.CITATION,
        user=current_user,
    )

    artifacts = [
        ProjectArtifactResponse(
            id=artifact.id,
            kind="citation",
            payload=ProjectCitationArtifactPayload.model_validate(artifact.payload),
            is_shared=artifact.is_shared,
            created_by_id=artifact.user_id,
            created_at=artifact.created_at,
        )
        for artifact in rows
    ]

    return ProjectArtifactListResponse(artifacts=artifacts)
