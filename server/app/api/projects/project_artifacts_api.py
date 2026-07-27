from starlette.responses import Response as ApiResponse
import logging
import uuid

from app.auth.dependencies import get_required_user
from app.database.crud.artifact_crud import artifact_crud
from app.database.database import get_db
from app.database.models import ArtifactKind
from app.schemas.user import CurrentUser
from app.policies.projects import get_project_access
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

project_artifacts_router = APIRouter()


@project_artifacts_router.get("/{project_id}")
async def get_project_artifacts(
    request: Request,
    project_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> ApiResponse:
    """
    Get chat-generated artifacts (citations) for a project.

    Project conversations are visible to every member, so their artifacts are
    too: any role in the project (admin/editor/viewer) grants read access.
    """
    project_uuid = uuid.UUID(project_id)
    if get_project_access(db, project_id=project_uuid, user_id=current_user.id) is None:
        return JSONResponse(status_code=404, content={"message": "Project not found"})

    rows = artifact_crud.list_for_project(
        db,
        project_id=project_uuid,
        kind=ArtifactKind.CITATION,
    )

    artifacts = [
        {
            "id": str(artifact.id),
            "kind": artifact.kind,
            "payload": artifact.payload,
            "message_id": str(artifact.message_id),
            "conversation_id": str(conversation_id),
            "conversation_title": conversation_title,
            "created_at": (
                artifact.created_at.isoformat() if artifact.created_at else None
            ),
        }
        for artifact, conversation_id, conversation_title in rows
    ]

    return JSONResponse(status_code=200, content={"artifacts": artifacts})
