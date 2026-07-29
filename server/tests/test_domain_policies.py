"""Table-driven contracts for framework-free business decisions."""

from __future__ import annotations

import pytest

from app.modules.conversations.domain import (
    ConversationAccessFacts,
    evaluate_conversation_access,
)
from app.modules.projects.domain import (
    ProjectAccessFacts,
    ProjectPermission,
    ProjectPermissions,
    require_grant_subset,
    require_permission,
)
from app.modules.research.domain import (
    ResearchAccessFacts,
    evaluate_research_access,
    require_research_manager,
)
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ConversationScopeType, ResearchScopeType


@pytest.mark.parametrize(
    ("facts", "permission", "allowed"),
    [
        (
            ProjectAccessFacts(1, 1, ProjectPermissions()),
            ProjectPermission.OWNER,
            True,
        ),
        (
            ProjectAccessFacts(
                2,
                1,
                ProjectPermissions(manage_papers=True),
            ),
            ProjectPermission.MANAGE_PAPERS,
            True,
        ),
        (
            ProjectAccessFacts(2, 1, ProjectPermissions()),
            ProjectPermission.EDIT_PROJECT,
            False,
        ),
    ],
)
def test_project_permission_decisions(
    facts: ProjectAccessFacts,
    permission: ProjectPermission,
    allowed: bool,
) -> None:
    if allowed:
        require_permission(facts, permission)
        return
    with pytest.raises(AppError) as error:
        require_permission(facts, permission)
    assert error.value.kind is FailureKind.PERMISSION_DENIED


def test_project_collaborator_cannot_grant_a_permission_they_do_not_have() -> None:
    access = ProjectAccessFacts(
        user_id=2,
        owner_id=1,
        permissions=ProjectPermissions(manage_papers=True),
    )
    with pytest.raises(AppError) as error:
        require_grant_subset(
            access,
            ProjectPermissions(manage_collaborators=True),
        )
    assert error.value.code == "project_permission_escalation"


@pytest.mark.parametrize(
    ("facts", "can_view", "can_manage"),
    [
        (
            ResearchAccessFacts(
                ResearchScopeType.PERSONAL,
                is_creator=True,
                is_shared=False,
                has_scope_access=True,
            ),
            True,
            True,
        ),
        (
            ResearchAccessFacts(
                ResearchScopeType.DOCUMENT,
                is_creator=False,
                is_shared=True,
                has_scope_access=True,
            ),
            True,
            False,
        ),
        (
            ResearchAccessFacts(
                ResearchScopeType.PROJECT,
                is_creator=True,
                is_shared=True,
                has_scope_access=False,
            ),
            True,
            False,
        ),
    ],
)
def test_research_visibility_decisions(
    facts: ResearchAccessFacts,
    can_view: bool,
    can_manage: bool,
) -> None:
    decision = evaluate_research_access(facts)
    assert decision.can_view is can_view
    assert decision.can_manage is can_manage


def test_research_creator_becomes_read_only_after_scope_access_is_lost() -> None:
    facts = ResearchAccessFacts(
        ResearchScopeType.PROJECT,
        is_creator=True,
        is_shared=True,
        has_scope_access=False,
    )
    decision = evaluate_research_access(facts)
    with pytest.raises(AppError) as error:
        require_research_manager(facts, decision)
    assert error.value.code == "research_item_scope_access_lost"


@pytest.mark.parametrize(
    ("facts", "can_continue", "reason"),
    [
        (
            ConversationAccessFacts(
                ConversationScopeType.GLOBAL,
                False,
                False,
                None,
                None,
            ),
            True,
            None,
        ),
        (
            ConversationAccessFacts(
                ConversationScopeType.PROJECT,
                True,
                True,
                "Current",
                "Snapshot",
            ),
            False,
            "project_deleted",
        ),
        (
            ConversationAccessFacts(
                ConversationScopeType.PAPER,
                False,
                False,
                None,
                "Paper",
            ),
            False,
            "scope_access_lost",
        ),
    ],
)
def test_conversation_scope_decisions(
    facts: ConversationAccessFacts,
    can_continue: bool,
    reason: str | None,
) -> None:
    decision = evaluate_conversation_access(facts)
    assert decision.can_continue is can_continue
    assert decision.read_only_reason == reason
