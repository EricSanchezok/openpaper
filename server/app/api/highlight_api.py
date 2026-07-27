from typing import Any
from uuid import UUID

from app.auth.dependencies import get_required_user
from app.database.crud.highlight_crud import (
    HighlightCreate,
    HighlightUpdate,
    highlight_crud,
)
from app.database.database import get_db
from app.database.models import RoleType
from app.database.telemetry import track_event
from app.errors import AppError
from app.schemas.orm_responses import serialize_highlight
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

highlight_router = APIRouter()


class CreateHighlightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    raw_text: str = Field(min_length=1, max_length=100_000)
    position: dict[str, Any] | None = None  # ScaledPosition JSON
    color: str | None = None  # Highlight color: yellow, green, blue, pink, purple
    # Text offsets support text-mode highlights; page_number supports PDF navigation.
    start_offset: int | None = None
    end_offset: int | None = None
    page_number: int | None = None
    project_id: UUID | None = None
    shared: bool | None = None

    @model_validator(mode="after")
    def validate_visibility(self) -> "CreateHighlightRequest":
        if self.project_id is None and self.shared:
            raise ValueError("Personal highlights cannot be shared")
        return self


class UpdateHighlightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = Field(min_length=1, max_length=100_000)
    position: dict[str, Any] | None = None  # ScaledPosition JSON
    color: str | None = None  # Highlight color: yellow, green, blue, pink, purple
    # Text offsets support text-mode highlights.
    start_offset: int | None = None
    end_offset: int | None = None


@highlight_router.post("")
async def create_highlight(
    request: CreateHighlightRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Create a new highlight for a document"""
    highlight = highlight_crud.create_scoped(
        db,
        obj_in=HighlightCreate(
            paper_id=request.paper_id,
            raw_text=request.raw_text,
            start_offset=request.start_offset,
            end_offset=request.end_offset,
            page_number=request.page_number,
            position=request.position,
            role=RoleType.USER,
            color=request.color,
            project_id=request.project_id,
            is_shared=(
                request.shared
                if request.shared is not None
                else request.project_id is not None
            ),
        ),
        user=current_user,
    )

    if highlight is None:
        raise AppError(
            code="highlight_create_failed",
            message="Highlight could not be created",
            status_code=500,
        )

    track_event("highlight_created", user_id=str(current_user.id), db=db)
    return JSONResponse(
        status_code=201,
        content=serialize_highlight(highlight),
    )


@highlight_router.get("/{paper_id}")
async def get_document_highlights(
    paper_id: UUID,
    project_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Get all highlights for a specific document"""
    highlights = highlight_crud.get_highlights_by_paper_id(
        db,
        paper_id=paper_id,
        user=current_user,
        project_id=project_id,
    )
    return JSONResponse(
        status_code=200,
        content=[serialize_highlight(highlight) for highlight in highlights],
    )


@highlight_router.delete("/{highlight_id}")
async def delete_highlight(
    highlight_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Delete a specific highlight"""
    existing_highlight = highlight_crud.get_for_mutation(
        db,
        highlight_id=highlight_id,
        user=current_user,
    )
    if existing_highlight is None:
        raise AppError(
            code="highlight_not_found",
            message="Highlight not found",
            status_code=404,
        )
    if existing_highlight.role == RoleType.ASSISTANT:
        raise AppError(
            code="assistant_highlight_immutable",
            message="Assistant highlights cannot be deleted",
            status_code=403,
        )

    highlight_crud.remove(db, id=highlight_id)
    return JSONResponse(
        status_code=200,
        content={"message": "Highlight deleted successfully"},
    )


@highlight_router.patch("/{highlight_id}")
async def update_highlight(
    highlight_id: UUID,
    request: UpdateHighlightRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    """Update an existing highlight"""
    existing_highlight = highlight_crud.get_for_mutation(
        db,
        highlight_id=highlight_id,
        user=current_user,
    )
    if existing_highlight is None:
        raise AppError(
            code="highlight_not_found",
            message="Highlight not found",
            status_code=404,
        )
    if existing_highlight.role == RoleType.ASSISTANT:
        raise AppError(
            code="assistant_highlight_immutable",
            message="Assistant highlights cannot be updated",
            status_code=403,
        )

    highlight = highlight_crud.update(
        db,
        db_obj=existing_highlight,
        obj_in=HighlightUpdate(
            paper_id=existing_highlight.paper_id,
            raw_text=request.raw_text,
            start_offset=request.start_offset,
            end_offset=request.end_offset,
            position=request.position,
            color=request.color,
            project_id=existing_highlight.project_id,
            is_shared=existing_highlight.is_shared,
        ),
    )
    if highlight is None:
        raise AppError(
            code="highlight_update_failed",
            message="Highlight could not be updated",
            status_code=500,
        )

    track_event("highlight_updated", user_id=str(current_user.id), db=db)
    return JSONResponse(status_code=200, content=serialize_highlight(highlight))
