"""CRUD for first-party artifacts (citations today; charts/images later)."""

import uuid
from typing import Any

from app.database.crud.base_crud import CRUDBase
from app.database.models import (
    Artifact,
    ArtifactKind,
    ConversableType,
    Conversation,
    Message,
)
from app.policies.research import require_project_research_access
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class ArtifactCreate(BaseModel):
    kind: ArtifactKind
    payload: dict[str, Any]
    message_id: uuid.UUID
    scope_type: str  # ConversableType value
    scope_id: uuid.UUID | None = None
    is_shared: bool = False


class ArtifactUpdate(BaseModel):
    payload: dict[str, Any] | None = None


class ArtifactCRUD(CRUDBase[Artifact, ArtifactCreate, ArtifactUpdate]):
    """CRUD for the artifacts table."""

    def create_for_message(
        self,
        db: Session,
        *,
        message: Message,
        conversation: Conversation,
        kind: ArtifactKind,
        payload: dict[str, Any],
        user: CurrentUser,
    ) -> Artifact | None:
        """Insert a single artifact, copying scope from the parent conversation."""
        obj_in = ArtifactCreate(
            kind=kind,
            payload=payload,
            message_id=message.id,
            scope_type=str(conversation.conversable_type),
            scope_id=conversation.conversable_id,
            is_shared=(conversation.conversable_type == ConversableType.PROJECT.value),
        )
        return self.create(db, obj_in=obj_in, user=user)

    def bulk_create_for_message(
        self,
        db: Session,
        *,
        message: Message,
        conversation: Conversation,
        items: list[tuple[ArtifactKind, dict[str, Any]]],
        user: CurrentUser,
    ) -> list[Artifact]:
        """Insert several artifacts for one assistant message in a single commit."""
        created: list[Artifact] = []
        for kind, payload in items:
            obj = self.create_for_message(
                db,
                message=message,
                conversation=conversation,
                kind=kind,
                payload=payload,
                user=user,
            )
            if obj is not None:
                created.append(obj)
        return created

    def list_for_project(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        kind: ArtifactKind | None = None,
        limit: int = 200,
        offset: int = 0,
        user: CurrentUser,
    ) -> list[Artifact]:
        """List shared project artifacts plus the requester's hidden artifacts.

        The originating conversation remains private and is intentionally not
        joined or returned.
        """
        access = require_project_research_access(
            db,
            project_id=project_id,
            user_id=user.id,
        )
        statement = select(Artifact).where(
            Artifact.scope_type == ConversableType.PROJECT.value,
            Artifact.scope_id == project_id,
        )
        if not access.is_owner:
            statement = statement.where(
                (Artifact.is_shared.is_(True)) | (Artifact.user_id == user.id),
            )
        if kind is not None:
            statement = statement.where(Artifact.kind == kind.value)
        statement = (
            statement.order_by(Artifact.created_at.desc()).offset(offset).limit(limit)
        )
        return list(db.scalars(statement).all())


artifact_crud = ArtifactCRUD(Artifact)
