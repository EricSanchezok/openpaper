"""One visibility command for every top-level Project research output."""

from __future__ import annotations

import uuid
from enum import Enum

from app.database.models import (
    Artifact,
    AudioOverview,
    ConversableType,
    DataTableExtractionJob,
    Highlight,
    PaperNote,
)
from app.errors import AppError
from app.policies.research import (
    require_project_research_access,
    require_research_item_manager,
)
from app.schemas.user import CurrentUser
from sqlalchemy.orm import Session

ResearchOutput = (
    Artifact | AudioOverview | DataTableExtractionJob | Highlight | PaperNote
)


class ResearchOutputKind(str, Enum):
    ARTIFACT = "artifact"
    AUDIO = "audio"
    DATA_TABLE = "data_table"
    HIGHLIGHT = "highlight"
    NOTE = "note"


def _load_output(
    db: Session,
    *,
    kind: ResearchOutputKind,
    output_id: uuid.UUID,
) -> ResearchOutput | None:
    if kind == ResearchOutputKind.ARTIFACT:
        return db.get(Artifact, output_id)
    if kind == ResearchOutputKind.AUDIO:
        return db.get(AudioOverview, output_id)
    if kind == ResearchOutputKind.DATA_TABLE:
        return db.get(DataTableExtractionJob, output_id)
    if kind == ResearchOutputKind.HIGHLIGHT:
        return db.get(Highlight, output_id)
    return db.get(PaperNote, output_id)


def _project_id(output: ResearchOutput) -> uuid.UUID | None:
    if isinstance(output, Artifact):
        if output.scope_type != ConversableType.PROJECT.value:
            return None
        return output.scope_id
    if isinstance(output, AudioOverview):
        if output.conversable_type != ConversableType.PROJECT.value:
            return None
        return output.conversable_id
    if isinstance(output, DataTableExtractionJob):
        return output.project_id
    return output.project_id


def set_research_output_visibility(
    db: Session,
    *,
    kind: ResearchOutputKind,
    output_id: uuid.UUID,
    shared: bool,
    user: CurrentUser,
) -> ResearchOutput:
    output = _load_output(db, kind=kind, output_id=output_id)
    if output is None:
        raise AppError(
            code="research_item_not_found",
            message="Research item not found",
            status_code=404,
        )
    project_id = _project_id(output)
    if project_id is None:
        raise AppError(
            code="research_item_not_project_scoped",
            message="Only Project research items can be shared",
            status_code=409,
        )
    access = require_project_research_access(
        db,
        project_id=project_id,
        user_id=user.id,
    )
    require_research_item_manager(
        access=access,
        created_by_id=output.user_id,
    )
    output.is_shared = shared
    db.commit()
    db.refresh(output)
    return output
