"""Pure Conversation context availability decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ConversationScopeType

ConversationReadOnlyReason = Literal[
    "scope_access_lost",
    "project_deleted",
    "document_deleted",
]


@dataclass(frozen=True, slots=True)
class ConversationAccessFacts:
    scope_type: ConversationScopeType
    context_deleted: bool
    has_scope_access: bool
    resolved_scope_label: str | None
    scope_label_snapshot: str | None


@dataclass(frozen=True, slots=True)
class ConversationAccessDecision:
    scope_label: str | None
    can_continue: bool
    read_only_reason: ConversationReadOnlyReason | None


def evaluate_conversation_access(
    facts: ConversationAccessFacts,
) -> ConversationAccessDecision:
    if facts.scope_type is ConversationScopeType.GLOBAL:
        return ConversationAccessDecision(None, True, None)
    if facts.context_deleted:
        reason: ConversationReadOnlyReason = (
            "project_deleted"
            if facts.scope_type is ConversationScopeType.PROJECT
            else "document_deleted"
        )
        return ConversationAccessDecision(
            facts.scope_label_snapshot,
            False,
            reason,
        )
    if not facts.has_scope_access:
        return ConversationAccessDecision(
            facts.scope_label_snapshot,
            False,
            "scope_access_lost",
        )
    return ConversationAccessDecision(
        facts.resolved_scope_label or facts.scope_label_snapshot,
        True,
        None,
    )


def require_conversation_continuable(
    decision: ConversationAccessDecision,
) -> None:
    if not decision.can_continue:
        raise AppError(
            code=decision.read_only_reason or "conversation_read_only",
            message="This conversation is read-only because its context is unavailable",
            kind=FailureKind.CONFLICT,
        )
