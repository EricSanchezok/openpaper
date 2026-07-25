import logging
from datetime import datetime, timezone
from typing import Generic, TypeVar

from app.database.crud.sanitization import sanitize_for_postgres
from app.database.models import Base
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

# Type variable for SQLAlchemy models
ModelType = TypeVar("ModelType", bound=Base)
CreateSchemaType = TypeVar("CreateSchemaType", bound=BaseModel)
UpdateSchemaType = TypeVar("UpdateSchemaType", bound=BaseModel)

logger = logging.getLogger(__name__)


def _get_sanitized_field_names(data: dict[str, object]) -> list[str]:
    sanitized_fields: list[str] = []
    for field, value in data.items():
        if sanitize_for_postgres(value) != value:
            sanitized_fields.append(field)
    return sanitized_fields


# Generic CRUD base class with type safety
class CRUDBase(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    def __init__(self, model: type[ModelType]):
        """
        CRUD object with default methods to Create, Read, Update, Delete
        """
        self.model = model

    def _filter_by_user(
        self,
        statement: Select[tuple[ModelType]],
        user: CurrentUser | None = None,
    ) -> Select[tuple[ModelType]]:
        """Add user filter to query if model has user_id and user is provided"""
        if user and hasattr(self.model, "user_id"):
            return statement.where(getattr(self.model, "user_id") == user.id)
        return statement

    def get(
        self,
        db: Session,
        id: object,
        *,
        user: CurrentUser | None = None,
        update_last_accessed: bool = False,
    ) -> ModelType | None:
        """Get a single record by ID, optionally filtered by user"""
        try:
            statement = select(self.model).where(getattr(self.model, "id") == id)
            statement = self._filter_by_user(statement, user)
            obj = db.scalars(statement).first()
            if obj and update_last_accessed and hasattr(obj, "last_accessed_at"):
                setattr(obj, "last_accessed_at", datetime.now(timezone.utc))
                db.commit()
                db.refresh(obj)
            return obj
        except Exception as e:
            # Roll back so a failed (often auto-)flush doesn't leave the session
            # stuck in PendingRollbackError for every subsequent operation.
            db.rollback()
            logger.error(
                f"Error retrieving {self.model.__name__} with ID {id}: {str(e)}",
                exc_info=True,
            )
            return None

    def get_multi(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        user: CurrentUser | None = None,
    ) -> list[ModelType]:
        """Get multiple records with pagination, optionally filtered by user"""
        try:
            statement = self._filter_by_user(select(self.model), user)
            return list(db.scalars(statement.offset(skip).limit(limit)).all())
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error retrieving multiple {self.model.__name__} objects: {str(e)}",
                exc_info=True,
            )
            return []

    def get_by(
        self,
        db: Session,
        *,
        user: CurrentUser | None = None,
        **filters: object,
    ) -> ModelType | None:
        """Get a single record by arbitrary filters"""
        try:
            statement = self._filter_by_user(select(self.model), user)

            # Apply filters
            for field, value in filters.items():
                if hasattr(self.model, field):
                    statement = statement.where(getattr(self.model, field) == value)

            return db.scalars(statement).first()
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error retrieving {self.model.__name__} with filters {filters}: {str(e)}",
                exc_info=True,
            )
            return None

    def get_multi_by(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        user: CurrentUser | None = None,
        **filters: object,
    ) -> list[ModelType]:
        """Get multiple records by arbitrary filters"""
        try:
            statement = self._filter_by_user(select(self.model), user)

            # Apply filters
            for field, value in filters.items():
                if hasattr(self.model, field):
                    statement = statement.where(getattr(self.model, field) == value)

            return list(db.scalars(statement.offset(skip).limit(limit)).all())
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error retrieving multiple {self.model.__name__} objects with filters {filters}: {str(e)}",
                exc_info=True,
            )
            return []

    def create(
        self,
        db: Session,
        *,
        obj_in: CreateSchemaType,
        user: CurrentUser | None = None,
        auto_commit: bool = True,
    ) -> ModelType | None:
        """Create a new record, optionally associating with a user.
        Set auto_commit=False to flush without committing, allowing the caller to
        batch multiple operations into a single transaction.
        """
        try:
            obj_in_data = obj_in.model_dump()
            if user and hasattr(self.model, "user_id"):
                obj_in_data["user_id"] = user.id
            sanitized_fields = _get_sanitized_field_names(obj_in_data)
            obj_in_data = sanitize_for_postgres(obj_in_data)
            if sanitized_fields:
                logger.warning(
                    "Sanitized null characters before creating %s in fields: %s",
                    self.model.__name__,
                    ", ".join(sanitized_fields),
                )
            db_obj = self.model(**obj_in_data)
            db.add(db_obj)
            if auto_commit:
                db.commit()
            else:
                db.flush()
            db.refresh(db_obj)
            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(
                f"Error creating {self.model.__name__}: {str(e)}", exc_info=True
            )
            return None

    def update(
        self,
        db: Session,
        *,
        db_obj: ModelType,
        obj_in: UpdateSchemaType | dict[str, object],
        user: CurrentUser | None = None,
    ) -> ModelType | None:
        """Update a record, verifying user ownership if specified"""
        if user and hasattr(db_obj, "user_id") and db_obj.user_id != user.id:
            logger.warning(
                f"User {user.id} attempted to update {self.model.__name__} owned by another user"
            )
            return None

        try:
            if isinstance(obj_in, dict):
                update_data = obj_in
            else:
                update_data = obj_in.model_dump(exclude_unset=True)

            sanitized_fields = _get_sanitized_field_names(update_data)
            update_data = sanitize_for_postgres(update_data)
            if sanitized_fields:
                logger.warning(
                    "Sanitized null characters before updating %s %s in fields: %s",
                    self.model.__name__,
                    getattr(db_obj, "id", None),
                    ", ".join(sanitized_fields),
                )

            for field in update_data:
                if hasattr(db_obj, field):
                    setattr(db_obj, field, update_data[field])

            db.add(db_obj)
            db.commit()
            db.refresh(db_obj)
            return db_obj
        except Exception as e:
            db.rollback()
            logger.error(
                "Error updating %s with ID %s: %s",
                self.model.__name__,
                getattr(db_obj, "id", None),
                e,
                exc_info=True,
            )
            return None

    def remove(
        self, db: Session, *, id: object, user: CurrentUser | None = None
    ) -> ModelType | None:
        """Delete a record, optionally verifying user ownership"""
        try:
            statement = select(self.model).where(getattr(self.model, "id") == id)
            statement = self._filter_by_user(statement, user)
            obj = db.scalars(statement).first()
            if obj:
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

    def has_any(
        self,
        db: Session,
        *,
        user: CurrentUser,
    ) -> bool:
        """Check if any records exist, optionally filtered by user"""
        try:
            statement = self._filter_by_user(select(self.model), user).limit(1)
            count = db.execute(
                select(func.count()).select_from(statement.subquery())
            ).scalar_one()
            return count > 0
        except Exception as e:
            logger.error(
                f"Error checking if any {self.model.__name__} objects exist: {str(e)}",
                exc_info=True,
            )
            return False
