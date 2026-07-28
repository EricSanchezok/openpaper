"""Typed persistence for user-owned conversations."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime, timezone

from app.database.models import Conversation, ConversationScopeType
from app.errors import AppError
from app.policies.conversations import conversation_policy
from app.policies.documents import get_document_access
from app.policies.projects import get_project_access
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
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> Conversation:
        statement = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        conversation = db.scalar(statement)
        if conversation is None:
            raise _not_found()
        return conversation

    def summarize(
        self,
        db: Session,
        *,
        conversation: Conversation,
    ) -> ConversationSummaryResponse:
        access = conversation_policy.evaluate(db, conversation=conversation)
        scope_type = ConversationScopeType(conversation.scope_type)
        scope_id = (
            conversation.project_id
            if scope_type == ConversationScopeType.PROJECT
            else conversation.document_id
            if scope_type == ConversationScopeType.PAPER
            else None
        )
        return ConversationSummaryResponse(
            id=conversation.id,
            title=conversation.title,
            updated_at=conversation.updated_at,
            scope_type=scope_type,
            scope_id=scope_id,
            scope_label=access.scope_label,
            scope_access="active" if access.can_continue else "lost",
            read_only=not access.can_continue,
            read_only_reason=access.read_only_reason,
            pinned_at=conversation.pinned_at,
            archived_at=conversation.archived_at,
            capabilities=ConversationCapabilitiesResponse(
                move=(
                    scope_type != ConversationScopeType.PAPER and access.can_continue
                ),
                detach=(
                    scope_type == ConversationScopeType.PROJECT and access.can_continue
                ),
                send=access.can_continue,
            ),
        )

    def create(
        self,
        db: Session,
        *,
        request: ConversationCreateRequest,
        user_id: int,
        auto_commit: bool = True,
    ) -> Conversation:
        project_id: uuid.UUID | None = None
        document_id: uuid.UUID | None = None
        scope_label: str | None = None
        if request.scope_type == ConversationScopeType.PROJECT:
            assert request.scope_id is not None
            access = get_project_access(
                db,
                project_id=request.scope_id,
                user_id=user_id,
            )
            if access is None:
                raise AppError(
                    code="project_not_found",
                    message="Project not found",
                    status_code=404,
                )
            project_id = request.scope_id
            scope_label = access.project.title
        elif request.scope_type == ConversationScopeType.PAPER:
            assert request.scope_id is not None
            document_access = get_document_access(
                db,
                document_id=request.scope_id,
                user_id=user_id,
            )
            if document_access is None:
                raise AppError(
                    code="paper_not_found",
                    message="Paper not found",
                    status_code=404,
                )
            document_id = request.scope_id
            scope_label = document_access.document.title

        conversation = Conversation(
            title=request.title,
            user_id=user_id,
            scope_type=request.scope_type.value,
            project_id=project_id,
            document_id=document_id,
            scope_label_snapshot=scope_label,
        )
        db.add(conversation)
        if auto_commit:
            db.commit()
            db.refresh(conversation)
        else:
            db.flush()
        return conversation

    def list(
        self,
        db: Session,
        *,
        user_id: int,
        archived: bool,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[Conversation], str | None]:
        statement = select(Conversation).where(
            Conversation.user_id == user_id,
            (
                Conversation.archived_at.isnot(None)
                if archived
                else Conversation.archived_at.is_(None)
            ),
        )
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
        return conversations, (
            _encode_cursor(conversations[-1]) if has_more and conversations else None
        )

    def update(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
        request: ConversationUpdateRequest,
    ) -> Conversation:
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        if request.title is not None:
            conversation.title = request.title
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
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        conversation_policy.require_can_continue(db, conversation=conversation)
        if conversation.scope_type == ConversationScopeType.PAPER.value:
            raise AppError(
                code="paper_conversation_scope_fixed",
                message="Paper conversations cannot change scope",
                status_code=409,
            )

        if request.scope_type == ConversationScopeType.PROJECT.value:
            assert request.scope_id is not None
            access = get_project_access(
                db,
                project_id=request.scope_id,
                user_id=user_id,
            )
            if access is None:
                raise AppError(
                    code="project_not_found",
                    message="Project not found",
                    status_code=404,
                )
            conversation.scope_type = ConversationScopeType.PROJECT.value
            conversation.project_id = request.scope_id
            conversation.document_id = None
            conversation.scope_label_snapshot = access.project.title
        else:
            conversation.scope_type = ConversationScopeType.GLOBAL.value
            conversation.project_id = None
            conversation.document_id = None
            conversation.scope_label_snapshot = None
        db.commit()
        db.refresh(conversation)
        return conversation

    def delete(
        self,
        db: Session,
        *,
        conversation_id: uuid.UUID,
        user_id: int,
    ) -> None:
        conversation = self.require_owned(
            db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        db.delete(conversation)
        db.commit()


conversation_repository = ConversationRepository()
