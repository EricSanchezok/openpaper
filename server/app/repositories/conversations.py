from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime, timezone

from app.database.models import (
    ConversableType,
    Conversation,
    Document,
    LibraryPaper,
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from app.errors import AppError
from app.policies.projects import get_project_access
from app.policies.documents import get_document_access
from app.schemas.conversations import (
    ConversationCapabilitiesResponse,
    ConversationCreateRequest,
    ConversationMoveRequest,
    ConversationSummaryResponse,
    ConversationUpdateRequest,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session


def _not_found() -> AppError:
    return AppError(
        code="conversation_not_found",
        message="Conversation not found",
        status_code=404,
    )


def _encode_cursor(conversation: Conversation) -> str:
    payload = json.dumps(
        {
            "p": (
                conversation.pinned_at.isoformat() if conversation.pinned_at else None
            ),
            "u": conversation.updated_at.isoformat(),
            "i": str(conversation.id),
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime | None, datetime, uuid.UUID]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode())
        pinned_at = datetime.fromisoformat(payload["p"]) if payload["p"] else None
        return pinned_at, datetime.fromisoformat(payload["u"]), uuid.UUID(payload["i"])
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise AppError(
            code="conversation_cursor_invalid",
            message="Conversation cursor is invalid",
            status_code=422,
        ) from exc


class ConversationRepository:
    def require_owned(
        self, db: Session, *, conversation_id: uuid.UUID, user_id: int
    ) -> Conversation:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        if conversation is None:
            raise _not_found()
        return conversation

    def _scope_label_and_access(
        self, db: Session, *, conversation: Conversation
    ) -> tuple[str | None, bool]:
        if conversation.conversable_type == ConversableType.EVERYTHING:
            return None, True
        if conversation.conversable_type == ConversableType.PROJECT:
            if conversation.conversable_id is None:
                raise RuntimeError("Project conversation has no project id")
            access = get_project_access(
                db,
                project_id=conversation.conversable_id,
                user_id=conversation.user_id,
            )
            return (
                access.project.title
                if access is not None
                else conversation.scope_label_snapshot,
                access is not None,
            )
        if conversation.conversable_id is None:
            raise RuntimeError("Paper conversation has no paper id")
        document_access = get_document_access(
            db,
            document_id=conversation.conversable_id,
            user_id=conversation.user_id,
        )
        return (
            (
                document_access.document.title
                if document_access is not None
                else conversation.scope_label_snapshot
            ),
            document_access is not None,
        )

    def summarize(
        self, db: Session, *, conversation: Conversation
    ) -> ConversationSummaryResponse:
        scope_label, has_scope_access = self._scope_label_and_access(
            db, conversation=conversation
        )
        is_project = conversation.conversable_type == ConversableType.PROJECT
        is_paper = conversation.conversable_type == ConversableType.PAPER
        return ConversationSummaryResponse(
            id=conversation.id,
            title=conversation.title,
            updated_at=conversation.updated_at,
            conversable_type=ConversableType(conversation.conversable_type),
            conversable_id=conversation.conversable_id,
            scope_label=scope_label,
            scope_access="active" if has_scope_access else "lost",
            pinned_at=conversation.pinned_at,
            archived_at=conversation.archived_at,
            capabilities=ConversationCapabilitiesResponse(
                move=not is_paper and has_scope_access,
                detach=is_project,
                send=has_scope_access,
            ),
        )

    def summarize_many(
        self,
        db: Session,
        *,
        conversations: list[Conversation],
        user_id: int,
    ) -> list[ConversationSummaryResponse]:
        """Serialize a sidebar page without issuing one scope query per row."""
        project_ids = {
            conversation.conversable_id
            for conversation in conversations
            if conversation.conversable_type == ConversableType.PROJECT
            and conversation.conversable_id is not None
        }
        paper_ids = {
            conversation.conversable_id
            for conversation in conversations
            if conversation.conversable_type == ConversableType.PAPER
            and conversation.conversable_id is not None
        }

        project_labels: dict[uuid.UUID, str] = {}
        if project_ids:
            project_rows = db.execute(
                select(Project.id, Project.title)
                .outerjoin(
                    ProjectCollaborator,
                    and_(
                        ProjectCollaborator.project_id == Project.id,
                        ProjectCollaborator.user_id == user_id,
                    ),
                )
                .where(
                    Project.id.in_(project_ids),
                    or_(
                        Project.owner_id == user_id,
                        ProjectCollaborator.user_id == user_id,
                    ),
                )
            ).all()
            project_labels = {project_id: title for project_id, title in project_rows}

        paper_labels: dict[uuid.UUID, str | None] = {}
        if paper_ids:
            library_document_ids = set(
                db.scalars(
                    select(LibraryPaper.document_id).where(
                        LibraryPaper.user_id == user_id,
                        LibraryPaper.document_id.in_(paper_ids),
                    )
                ).all()
            )
            project_document_ids = set(
                db.scalars(
                    select(ProjectPaper.document_id)
                    .join(Project, Project.id == ProjectPaper.project_id)
                    .outerjoin(
                        ProjectCollaborator,
                        and_(
                            ProjectCollaborator.project_id == Project.id,
                            ProjectCollaborator.user_id == user_id,
                        ),
                    )
                    .where(
                        ProjectPaper.document_id.in_(paper_ids),
                        or_(
                            Project.owner_id == user_id,
                            ProjectCollaborator.user_id == user_id,
                        ),
                    )
                ).all()
            )
            accessible_document_ids = library_document_ids | project_document_ids
            paper_rows = db.execute(
                select(Document.id, Document.title).where(
                    Document.id.in_(accessible_document_ids)
                )
            ).all()
            paper_labels = {paper_id: title for paper_id, title in paper_rows}

        summaries: list[ConversationSummaryResponse] = []
        for conversation in conversations:
            scope_label: str | None = None
            has_scope_access = True
            if conversation.conversable_type == ConversableType.PROJECT:
                assert conversation.conversable_id is not None
                scope_label = project_labels.get(
                    conversation.conversable_id,
                    conversation.scope_label_snapshot,
                )
                has_scope_access = conversation.conversable_id in project_labels
            elif conversation.conversable_type == ConversableType.PAPER:
                assert conversation.conversable_id is not None
                scope_label = paper_labels.get(
                    conversation.conversable_id,
                    conversation.scope_label_snapshot,
                )
                has_scope_access = conversation.conversable_id in paper_labels

            is_project = conversation.conversable_type == ConversableType.PROJECT
            is_paper = conversation.conversable_type == ConversableType.PAPER
            summaries.append(
                ConversationSummaryResponse(
                    id=conversation.id,
                    title=conversation.title,
                    updated_at=conversation.updated_at,
                    conversable_type=ConversableType(conversation.conversable_type),
                    conversable_id=conversation.conversable_id,
                    scope_label=scope_label,
                    scope_access="active" if has_scope_access else "lost",
                    pinned_at=conversation.pinned_at,
                    archived_at=conversation.archived_at,
                    capabilities=ConversationCapabilitiesResponse(
                        move=not is_paper and has_scope_access,
                        detach=is_project,
                        send=has_scope_access,
                    ),
                )
            )
        return summaries

    def create(
        self,
        db: Session,
        *,
        request: ConversationCreateRequest,
        user_id: int,
    ) -> Conversation:
        scope_label: str | None = None
        if request.conversable_type == ConversableType.PROJECT:
            assert request.conversable_id is not None
            access = get_project_access(
                db, project_id=request.conversable_id, user_id=user_id
            )
            if access is None:
                raise AppError(
                    code="project_not_found",
                    message="Project not found",
                    status_code=404,
                )
            scope_label = access.project.title
        elif request.conversable_type == ConversableType.PAPER:
            assert request.conversable_id is not None
            document_access = get_document_access(
                db,
                document_id=request.conversable_id,
                user_id=user_id,
            )
            if document_access is None:
                raise AppError(
                    code="paper_not_found",
                    message="Paper not found",
                    status_code=404,
                )
            scope_label = document_access.document.title

        conversation = Conversation(
            title=request.title.strip(),
            user_id=user_id,
            conversable_type=request.conversable_type,
            conversable_id=request.conversable_id,
            scope_label_snapshot=scope_label,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    def list(
        self,
        db: Session,
        *,
        user_id: int,
        archived: bool,
        limit: int,
        cursor: str | None,
        conversable_type: ConversableType | None = None,
        conversable_id: uuid.UUID | None = None,
    ) -> tuple[list[Conversation], str | None]:
        statement = select(Conversation).where(
            Conversation.user_id == user_id,
            (
                Conversation.archived_at.isnot(None)
                if archived
                else Conversation.archived_at.is_(None)
            ),
        )
        if conversable_type is not None:
            statement = statement.where(
                Conversation.conversable_type == conversable_type
            )
        if conversable_id is not None:
            statement = statement.where(Conversation.conversable_id == conversable_id)
        if cursor:
            pinned_at, updated_at, conversation_id = _decode_cursor(cursor)
            if pinned_at is not None:
                statement = statement.where(
                    or_(
                        Conversation.pinned_at.is_(None),
                        Conversation.pinned_at < pinned_at,
                        and_(
                            Conversation.pinned_at == pinned_at,
                            or_(
                                Conversation.updated_at < updated_at,
                                and_(
                                    Conversation.updated_at == updated_at,
                                    Conversation.id < conversation_id,
                                ),
                            ),
                        ),
                    )
                )
            else:
                statement = statement.where(
                    Conversation.pinned_at.is_(None),
                    or_(
                        Conversation.updated_at < updated_at,
                        and_(
                            Conversation.updated_at == updated_at,
                            Conversation.id < conversation_id,
                        ),
                    ),
                )
        conversations = list(
            db.scalars(
                statement.order_by(
                    Conversation.pinned_at.desc().nulls_last(),
                    Conversation.updated_at.desc(),
                    Conversation.id.desc(),
                ).limit(limit + 1)
            ).all()
        )
        has_more = len(conversations) > limit
        conversations = conversations[:limit]
        next_cursor = (
            _encode_cursor(conversations[-1]) if has_more and conversations else None
        )
        return conversations, next_cursor

    def update(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        request: ConversationUpdateRequest,
    ) -> Conversation:
        conversation = self.require_owned(
            db, conversation_id=conversation_id, user_id=user_id
        )
        if request.title is not None:
            conversation.title = request.title.strip()
        if request.pinned is not None:
            conversation.pinned_at = (
                datetime.now(timezone.utc) if request.pinned else None
            )
        if request.archived is not None:
            conversation.archived_at = (
                datetime.now(timezone.utc) if request.archived else None
            )
            if request.archived:
                conversation.pinned_at = None
        db.commit()
        db.refresh(conversation)
        return conversation

    def move(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        request: ConversationMoveRequest,
    ) -> Conversation:
        conversation = self.require_owned(
            db, conversation_id=conversation_id, user_id=user_id
        )
        if conversation.conversable_type == ConversableType.PAPER:
            raise AppError(
                code="paper_conversation_scope_fixed",
                message="Paper conversations cannot change scope",
                status_code=409,
            )
        if request.conversable_type == "project":
            assert request.conversable_id is not None
            access = get_project_access(
                db, project_id=request.conversable_id, user_id=user_id
            )
            if access is None:
                raise AppError(
                    code="project_not_found",
                    message="Project not found",
                    status_code=404,
                )
            conversation.conversable_type = ConversableType.PROJECT
            conversation.conversable_id = request.conversable_id
            conversation.scope_label_snapshot = access.project.title
        else:
            conversation.conversable_type = ConversableType.EVERYTHING
            conversation.conversable_id = None
            conversation.scope_label_snapshot = None
        db.commit()
        db.refresh(conversation)
        return conversation

    def delete(self, db: Session, *, conversation_id: uuid.UUID, user_id: int) -> None:
        conversation = self.require_owned(
            db, conversation_id=conversation_id, user_id=user_id
        )
        db.delete(conversation)
        db.commit()


conversation_repository = ConversationRepository()
