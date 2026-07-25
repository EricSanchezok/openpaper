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

    def list_for_scope(
        self,
        db: Session,
        *,
        scope_type: str,
        scope_id: uuid.UUID | None,
        user: CurrentUser,
        kind: ArtifactKind | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Artifact]:
        """List artifacts in a given scope (e.g. project panel feed).

        Returns every occurrence; callers attach conversation breadcrumbs.
        Ownership is enforced via user_id.
        """
        statement = select(Artifact).where(
            Artifact.user_id == user.id,
            Artifact.scope_type == scope_type,
        )
        if scope_id is not None:
            statement = statement.where(Artifact.scope_id == scope_id)
        else:
            statement = statement.where(Artifact.scope_id.is_(None))
        if kind is not None:
            statement = statement.where(Artifact.kind == kind.value)
        statement = (
            statement.order_by(Artifact.created_at.desc()).offset(offset).limit(limit)
        )
        return list(db.scalars(statement).all())

    def list_for_project(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        kind: ArtifactKind | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[tuple[Artifact, uuid.UUID, str | None]]:
        """List artifacts across ALL members' conversations in a project.

        Deliberately no user_id filter: project conversations are visible to
        every member, so their artifacts are too. Callers MUST verify the
        requester holds a role in the project before calling this.

        Returns (artifact, conversation_id, conversation_title) so the panel
        can attach a breadcrumb back to the source conversation.
        """
        statement = (
            select(Artifact, Conversation.id, Conversation.title)
            .join(Message, Artifact.message_id == Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Artifact.scope_type == ConversableType.PROJECT.value,
                Artifact.scope_id == project_id,
            )
        )
        if kind is not None:
            statement = statement.where(Artifact.kind == kind.value)
        statement = (
            statement.order_by(Artifact.created_at.desc()).offset(offset).limit(limit)
        )
        return list(db.execute(statement).tuples().all())


artifact_crud = ArtifactCRUD(Artifact)
