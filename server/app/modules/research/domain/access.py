"""Pure visibility rules for Research items."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchScopeType


@dataclass(frozen=True, slots=True)
class ResearchAccessFacts:
    scope_type: ResearchScopeType
    is_creator: bool
    is_shared: bool
    has_scope_access: bool


@dataclass(frozen=True, slots=True)
class ResearchAccessDecision:
    can_view: bool
    can_manage: bool
    has_scope_access: bool


def evaluate_research_access(
    facts: ResearchAccessFacts,
) -> ResearchAccessDecision:
    if facts.scope_type is ResearchScopeType.PERSONAL:
        return ResearchAccessDecision(
            can_view=facts.is_creator,
            can_manage=facts.is_creator,
            has_scope_access=facts.is_creator,
        )
    return ResearchAccessDecision(
        can_view=facts.is_creator or (facts.is_shared and facts.has_scope_access),
        can_manage=facts.is_creator and facts.has_scope_access,
        has_scope_access=facts.has_scope_access,
    )


def require_research_visible(
    decision: ResearchAccessDecision,
) -> None:
    if not decision.can_view:
        raise AppError(
            code="research_item_not_found",
            message="Research item not found",
            kind=FailureKind.NOT_FOUND,
        )


def require_research_manager(
    facts: ResearchAccessFacts,
    decision: ResearchAccessDecision,
) -> None:
    require_research_visible(decision)
    if not facts.is_creator:
        raise AppError(
            code="research_item_permission_denied",
            message="Only the creator can modify this research item",
            kind=FailureKind.PERMISSION_DENIED,
        )
    if not decision.has_scope_access:
        raise AppError(
            code="research_item_scope_access_lost",
            message="This research item is read-only until scope access is restored",
            kind=FailureKind.CONFLICT,
        )
