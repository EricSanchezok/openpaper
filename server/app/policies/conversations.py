"""Authorization and lifecycle state for private conversations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.database.models import Conversation, ConversationScopeType
from app.errors import AppError
from app.policies.documents import get_document_access
from app.policies.projects import get_project_access
from sqlalchemy.orm import Session

ConversationReadOnlyReason = Literal[
    "scope_access_lost",
    "project_deleted",
    "document_deleted",
]


@dataclass(frozen=True, slots=True)
class ConversationAccess:
    scope_label: str | None
    can_continue: bool
    read_only_reason: ConversationReadOnlyReason | None


class ConversationPolicy:
    """The only place that interprets a Conversation's scope access."""

    def evaluate(
        self, db: Session, *, conversation: Conversation
    ) -> ConversationAccess:
        scope_type = ConversationScopeType(conversation.scope_type)
        if scope_type == ConversationScopeType.GLOBAL:
            return ConversationAccess(None, True, None)

        if conversation.context_deleted_at is not None:
            reason: ConversationReadOnlyReason = (
                "project_deleted"
                if scope_type == ConversationScopeType.PROJECT
                else "document_deleted"
            )
            return ConversationAccess(
                conversation.scope_label_snapshot,
                False,
                reason,
            )

        if scope_type == ConversationScopeType.PROJECT:
            if conversation.project_id is None:
                raise RuntimeError("active_project_conversation_missing_project")
            access = get_project_access(
                db,
                project_id=conversation.project_id,
                user_id=conversation.user_id,
            )
            return ConversationAccess(
                (
                    access.project.title
                    if access is not None
                    else conversation.scope_label_snapshot
                ),
                access is not None,
                None if access is not None else "scope_access_lost",
            )

        if conversation.document_id is None:
            raise RuntimeError("active_paper_conversation_missing_document")
        document_access = get_document_access(
            db,
            document_id=conversation.document_id,
            user_id=conversation.user_id,
        )
        return ConversationAccess(
            (
                document_access.document.title
                if document_access is not None
                else conversation.scope_label_snapshot
            ),
            document_access is not None,
            None if document_access is not None else "scope_access_lost",
        )

    def require_can_continue(
        self,
        db: Session,
        *,
        conversation: Conversation,
    ) -> ConversationAccess:
        access = self.evaluate(db, conversation=conversation)
        if access.can_continue:
            return access
        raise AppError(
            code=access.read_only_reason or "conversation_read_only",
            message="This conversation is read-only because its context is unavailable",
            status_code=409,
        )


conversation_policy = ConversationPolicy()
