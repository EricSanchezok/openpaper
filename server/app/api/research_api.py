from uuid import UUID

from app.auth.dependencies import get_required_user
from app.database.database import get_db
from app.schemas.user import CurrentUser
from app.services.research_visibility import (
    ResearchOutputKind,
    set_research_output_visibility,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

research_router = APIRouter()


class ResearchVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shared: bool


@research_router.patch("/{kind}/{output_id}/visibility")
def update_research_visibility(
    kind: ResearchOutputKind,
    output_id: UUID,
    request: ResearchVisibilityRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> dict[str, object]:
    output = set_research_output_visibility(
        db,
        kind=kind,
        output_id=output_id,
        shared=request.shared,
        user=current_user,
    )
    return {
        "kind": kind.value,
        "id": str(output.id),
        "shared": output.is_shared,
    }
