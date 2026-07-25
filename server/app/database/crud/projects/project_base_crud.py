import logging
from typing import Generic

from app.database.crud.base_crud import (
    CreateSchemaType,
    ModelType,
    UpdateSchemaType,
)
from app.database.models import Project, ProjectPaper, ProjectRole, ProjectRoles
from app.schemas.user import CurrentUser
from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ProjectBaseCRUD(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: type[ModelType]) -> None:
        self.model = model

    def _get_base_statement(self) -> Select[tuple[ModelType]]:
        if self.model == Project:
            return select(self.model)
        return select(self.model).join(
            Project, getattr(self.model, "project_id") == Project.id
        )

    def get(self, db: Session, id: object, *, user: CurrentUser) -> ModelType | None:
        statement = (
            self._get_base_statement()
            .join(ProjectRole, Project.id == ProjectRole.project_id)
            .where(getattr(self.model, "id") == id, ProjectRole.user_id == user.id)
        )
        return db.scalars(statement).first()

    def get_multi_by_user(
        self, db: Session, *, user: CurrentUser, skip: int = 0, limit: int = 100
    ) -> list[ModelType]:
        join_on = (
            Project.id if self.model == Project else getattr(self.model, "project_id")
        )
        statement = (
            self._get_base_statement()
            .join(ProjectRole, join_on == ProjectRole.project_id)
            .where(ProjectRole.user_id == user.id)
            .order_by(self.model.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(db.scalars(statement).all())

    def update(
        self,
        db: Session,
        *,
        id: object,
        obj_in: UpdateSchemaType | dict[str, object],
        user: CurrentUser,
    ) -> ModelType | None:
        try:
            statement = (
                self._get_base_statement()
                .join(ProjectRole, Project.id == ProjectRole.project_id)
                .where(
                    getattr(self.model, "id") == id,
                    ProjectRole.user_id == user.id,
                    ProjectRole.role.in_([ProjectRoles.ADMIN]),
                )
            )
            db_obj = db.scalars(statement).first()

            if not db_obj:
                return None

            if isinstance(obj_in, dict):
                update_data = obj_in
            else:
                update_data = obj_in.model_dump(exclude_unset=True)

            for field, value in update_data.items():
                setattr(db_obj, field, value)

            db.add(db_obj)
            db.commit()
            db.refresh(db_obj)
            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error updating {self.model.__name__} with ID {id}: {str(e)}",
                exc_info=True,
            )
            return None

    def remove(self, db: Session, *, id: object, user: CurrentUser) -> ModelType | None:
        try:
            statement = (
                self._get_base_statement()
                .join(ProjectRole, Project.id == ProjectRole.project_id)
                .where(
                    getattr(self.model, "id") == id,
                    ProjectRole.user_id == user.id,
                    ProjectRole.role.in_([ProjectRoles.ADMIN]),
                )
            )
            obj = db.scalars(statement).first()

            if obj:
                if self.model == Project:
                    project_id = getattr(obj, "id")

                    db.execute(
                        delete(ProjectPaper).where(
                            ProjectPaper.project_id == project_id
                        )
                    )
                    db.execute(
                        delete(ProjectRole).where(ProjectRole.project_id == project_id)
                    )

                db.delete(obj)
                db.commit()
                return obj
            return None
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error removing {self.model.__name__} with ID {id}: {str(e)}",
                exc_info=True,
            )
            return None
