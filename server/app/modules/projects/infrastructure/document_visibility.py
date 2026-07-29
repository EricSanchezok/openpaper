"""SQLAlchemy adapter for the public project-document visibility capability."""

from __future__ import annotations

from uuid import UUID

from app.modules.projects.infrastructure.models import (
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.shared.application import Actor
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session


class SqlProjectDocumentVisibility:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_accessible_document_ids(
        self,
        *,
        actor: Actor,
        project_id: UUID | None = None,
    ) -> tuple[UUID, ...]:
        statement = (
            select(ProjectPaper.document_id)
            .join(Project, Project.id == ProjectPaper.project_id)
            .outerjoin(
                ProjectCollaborator,
                and_(
                    ProjectCollaborator.project_id == Project.id,
                    ProjectCollaborator.user_id == actor.id,
                ),
            )
            .where(
                or_(
                    Project.owner_id == actor.id,
                    ProjectCollaborator.user_id == actor.id,
                )
            )
            .distinct()
        )
        if project_id is not None:
            statement = statement.where(Project.id == project_id)
        return tuple(self._db.scalars(statement).all())
