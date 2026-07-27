from __future__ import annotations

import uuid

from app.database.models import ConversableType, Conversation
from app.policies.projects import get_project_access
from app.repositories.projects import project_repository
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class ProjectConversationBase(BaseModel):
    title: str | None = None


class ProjectConversationCreate(ProjectConversationBase):
    pass


class ProjectConversationUpdate(ProjectConversationBase):
    pass


class ProjectConversationCRUD:
    def create(
        self,
        db: Session,
        *,
        obj_in: ProjectConversationCreate,
        user: CurrentUser | None = None,
        project_id: uuid.UUID | None = None,
    ) -> Conversation | None:
        if user is None:
            raise ValueError("user is required")
        if project_id is None:
            raise ValueError("project_id is required")
        if get_project_access(db, project_id=project_id, user_id=user.id) is None:
            return None

        conversation = Conversation(
            title=obj_in.title,
            user_id=user.id,
            conversable_id=project_id,
            conversable_type=ConversableType.PROJECT,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        project_repository.touch(db, project_id=project_id)
        return conversation

    def get_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: CurrentUser
    ) -> list[Conversation]:
        if get_project_access(db, project_id=project_id, user_id=user.id) is None:
            return []
        return list(
            db.scalars(
                select(Conversation)
                .where(
                    Conversation.conversable_id == project_id,
                    Conversation.conversable_type == ConversableType.PROJECT,
                    Conversation.user_id == user.id,
                )
                .order_by(Conversation.updated_at.desc())
            ).all()
        )

    def get_by_conversation_id(
        self,
        db: Session,
        *,
        project_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user: CurrentUser,
    ) -> Conversation | None:
        if get_project_access(db, project_id=project_id, user_id=user.id) is None:
            return None
        return db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.conversable_id == project_id,
                Conversation.conversable_type == ConversableType.PROJECT,
                Conversation.user_id == user.id,
            )
        )


project_conversation_crud = ProjectConversationCRUD()
