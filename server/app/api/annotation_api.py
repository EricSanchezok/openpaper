from uuid import UUID

from app.auth.dependencies import get_required_user
from app.database.crud.annotation_crud import (
    AnnotationCreate,
    AnnotationUpdate,
    annotation_crud,
)
from app.database.database import get_db
from app.database.models import RoleType
from app.database.telemetry import track_event
from app.errors import AppError
from app.schemas.orm_responses import serialize_annotation
from app.schemas.user import CurrentUser
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

annotation_router = APIRouter()


class CreateAnnotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper_id: UUID
    highlight_id: UUID
    content: str = Field(min_length=1, max_length=100_000)


class UpdateAnnotationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=100_000)


@annotation_router.post("")
async def create_annotation(
    request: CreateAnnotationRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    annotation = annotation_crud.create_for_highlight(
        db,
        obj_in=AnnotationCreate(
            paper_id=request.paper_id,
            highlight_id=request.highlight_id,
            content=request.content,
            role=RoleType.USER,
        ),
        user=current_user,
    )
    if annotation is None:
        raise AppError(
            code="highlight_not_found",
            message="Highlight not found",
            status_code=404,
        )

    track_event("annotation_created", user_id=str(current_user.id), db=db)
    return JSONResponse(
        status_code=201,
        content=serialize_annotation(annotation),
    )


@annotation_router.get("/{paper_id}")
async def get_document_annotations(
    paper_id: UUID,
    project_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    annotations = annotation_crud.get_annotations_by_paper_id(
        db,
        paper_id=paper_id,
        user=current_user,
        project_id=project_id,
    )
    return JSONResponse(
        status_code=200,
        content=[serialize_annotation(annotation) for annotation in annotations],
    )


@annotation_router.delete("/{annotation_id}")
async def delete_annotation(
    annotation_id: UUID,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    existing_annotation = annotation_crud.get_for_mutation(
        db,
        annotation_id=annotation_id,
        user=current_user,
    )
    if existing_annotation is None:
        raise AppError(
            code="annotation_not_found",
            message="Annotation not found",
            status_code=404,
        )
    if existing_annotation.role == RoleType.ASSISTANT:
        raise AppError(
            code="assistant_annotation_immutable",
            message="Assistant annotations cannot be deleted",
            status_code=403,
        )

    annotation_crud.remove(db, id=annotation_id)
    return JSONResponse(
        status_code=200,
        content={"message": "Annotation deleted successfully"},
    )


@annotation_router.patch("/{annotation_id}")
async def update_annotation(
    annotation_id: UUID,
    request: UpdateAnnotationRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> JSONResponse:
    existing_annotation = annotation_crud.get_for_mutation(
        db,
        annotation_id=annotation_id,
        user=current_user,
    )
    if existing_annotation is None:
        raise AppError(
            code="annotation_not_found",
            message="Annotation not found",
            status_code=404,
        )
    if existing_annotation.role == RoleType.ASSISTANT:
        raise AppError(
            code="assistant_annotation_immutable",
            message="Assistant annotations cannot be updated",
            status_code=403,
        )

    annotation = annotation_crud.update(
        db,
        db_obj=existing_annotation,
        obj_in=AnnotationUpdate(
            paper_id=existing_annotation.paper_id,
            highlight_id=existing_annotation.highlight_id,
            content=request.content,
        ),
    )
    if annotation is None:
        raise AppError(
            code="annotation_update_failed",
            message="Annotation could not be updated",
            status_code=500,
        )

    track_event("annotation_updated", user_id=str(current_user.id), db=db)
    return JSONResponse(status_code=200, content=serialize_annotation(annotation))
