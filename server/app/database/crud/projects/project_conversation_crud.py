import logging
import uuid

from app.database.crud.projects.project_base_crud import ProjectBaseCRUD
from app.database.crud.projects.project_crud import project_crud
from app.database.models import ConversableType, Conversation, ProjectRole, ProjectRoles
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ProjectConversationBase(BaseModel):
    title: str | None = None


class ProjectConversationCreate(ProjectConversationBase):
    pass


class ProjectConversationUpdate(ProjectConversationBase):
    pass


class ProjectConversationCRUD(
    ProjectBaseCRUD[Conversation, ProjectConversationCreate, ProjectConversationUpdate]
):
    def create(
        self,
        db: Session,
        *,
        obj_in: ProjectConversationCreate,
        user: CurrentUser | None = None,
        project_id: uuid.UUID | None = None,
    ) -> Conversation | None:
        # Validate required parameters for this implementation
        if user is None:
            raise ValueError(
                "user parameter is required for ProjectConversationCRUD.create"
            )
        if project_id is None:
            raise ValueError(
                "project_id parameter is required for ProjectConversationCRUD.create"
            )

        try:
            # Check if the user has permission to create in this project
            project_role = db.scalars(
                select(ProjectRole).where(
                    ProjectRole.project_id == project_id,
                    ProjectRole.user_id == user.id,
                    ProjectRole.role.in_([ProjectRoles.ADMIN, ProjectRoles.EDITOR]),
                )
            ).first()
            if not project_role:
                return None

            db_obj = Conversation(
                title=obj_in.title,
                user_id=user.id,
                conversable_id=project_id,
                conversable_type=ConversableType.PROJECT,
            )
            db.add(db_obj)
            db.commit()
            db.refresh(db_obj)

            # Touch project updated_at so it sorts to top of recent projects
            project_crud.touch(db, project_id)

            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error creating {self.model.__name__}: {str(e)}", exc_info=True
            )
            return None

    def get_by_project_id(
        self, db: Session, *, project_id: uuid.UUID, user: CurrentUser
    ) -> list[Conversation]:
        # First, check if the user has access to the project.
        project_role = db.scalars(
            select(ProjectRole).where(
                ProjectRole.project_id == project_id,
                ProjectRole.user_id == user.id,
            )
        ).first()
        if not project_role:
            return []

        return list(
            db.scalars(
                select(Conversation)
                .where(
                    Conversation.conversable_id == project_id,
                    Conversation.conversable_type == ConversableType.PROJECT,
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
        # First, check if the user has access to the project.
        project_role = db.scalars(
            select(ProjectRole).where(
                ProjectRole.project_id == project_id,
                ProjectRole.user_id == user.id,
            )
        ).first()
        if not project_role:
            return None

        return db.scalars(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.conversable_type == ConversableType.PROJECT,
            )
        ).first()


project_conversation_crud = ProjectConversationCRUD(Conversation)
