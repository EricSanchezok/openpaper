"""Cross-module authorization state for private conversations."""

from __future__ import annotations

from app.database.models import Conversation, ConversationScopeType
from app.modules.conversations.domain import (
    ConversationAccessDecision,
    ConversationAccessFacts,
    evaluate_conversation_access,
    require_conversation_continuable,
)
from app.modules.papers.infrastructure.access import get_document_access
from app.modules.projects.infrastructure.access import get_project_access
from sqlalchemy.orm import Session


class ConversationPolicy:
    """The only place that interprets a Conversation's scope access."""

    def evaluate(
        self, db: Session, *, conversation: Conversation
    ) -> ConversationAccessDecision:
        scope_type = ConversationScopeType(conversation.scope_type)
        resolved_scope_label: str | None = None
        has_scope_access = True
        if scope_type == ConversationScopeType.PROJECT:
            if conversation.project_id is None:
                raise RuntimeError("active_project_conversation_missing_project")
            access = get_project_access(
                db,
                project_id=conversation.project_id,
                user_id=conversation.user_id,
            )
            has_scope_access = access is not None
            resolved_scope_label = access.project.title if access is not None else None
        elif scope_type == ConversationScopeType.PAPER:
            if conversation.document_id is None:
                raise RuntimeError("active_paper_conversation_missing_document")
            document_access = get_document_access(
                db,
                document_id=conversation.document_id,
                user_id=conversation.user_id,
            )
            has_scope_access = document_access is not None
            resolved_scope_label = (
                document_access.document.title if document_access is not None else None
            )
        return evaluate_conversation_access(
            ConversationAccessFacts(
                scope_type=scope_type,
                context_deleted=conversation.context_deleted_at is not None,
                has_scope_access=has_scope_access,
                resolved_scope_label=resolved_scope_label,
                scope_label_snapshot=conversation.scope_label_snapshot,
            )
        )

    def require_can_continue(
        self,
        db: Session,
        *,
        conversation: Conversation,
    ) -> ConversationAccessDecision:
        access = self.evaluate(db, conversation=conversation)
        require_conversation_continuable(access)
        return access


conversation_policy = ConversationPolicy()
