"""
Subscription limits and enforcement utilities.

This module defines the subscription plans and their associated limits,
and provides functions to check if a user can perform certain actions
based on their subscription plan.
"""

import logging
import uuid
from datetime import datetime, timezone

from app.database.crud.paper_crud import paper_crud
from app.database.crud.projects.project_paper_crud import project_paper_crud
from app.database.crud.subscription_crud import subscription_crud
from app.database.models import AuthUser, Project, SubscriptionPlan, SubscriptionStatus
from app.database.telemetry import track_event
from app.policies.projects import get_project_access
from app.schemas.user import CurrentUser
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PAPER_UPLOAD_KEY = "paper_uploads"
KB_SIZE_KEY = "knowledge_base_size"
TOKEN_CREDITS_KEY = "token_credits_weekly"
PROJECTS_KEY = "projects"
PROJECT_PAPERS_KEY = "project_papers"

# Define subscription plan limits
SUBSCRIPTION_LIMITS: dict[SubscriptionPlan, dict[str, int]] = {
    SubscriptionPlan.BASIC: {
        PAPER_UPLOAD_KEY: 10,
        KB_SIZE_KEY: 200 * 1024,  # 200 MB in KB
        TOKEN_CREDITS_KEY: 3_000_000,
        PROJECTS_KEY: 2,
        PROJECT_PAPERS_KEY: 50,
    },
    SubscriptionPlan.RESEARCHER: {
        PAPER_UPLOAD_KEY: 500,
        KB_SIZE_KEY: 3 * 1024 * 1024,  # 3 GB in KB
        TOKEN_CREDITS_KEY: 100_000_000,
        PROJECTS_KEY: 100,
        PROJECT_PAPERS_KEY: 120,
    },
}
PLAN_LABELS = {
    SubscriptionPlan.BASIC: "Basic",
    SubscriptionPlan.RESEARCHER: "Researcher",
}


def get_user_subscription_plan(db: Session, user: CurrentUser) -> SubscriptionPlan:
    """
    Get the user's current subscription plan.
    Returns BASIC if no active subscription is found.
    """
    subscription = subscription_crud.get_by_user_id(db, user.id)

    if not subscription:
        return SubscriptionPlan.BASIC

    # Check if subscription is active and not expired
    if (
        subscription.current_period_end
        and subscription.current_period_end > datetime.now(timezone.utc)
    ):
        if subscription.status in [
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.TRIALING,
        ]:
            return SubscriptionPlan(subscription.plan)

    # If subscription is expired or inactive, return BASIC
    return SubscriptionPlan.BASIC


def get_plan_limits(plan: SubscriptionPlan) -> dict[str, int]:
    """Get the limits for a specific subscription plan."""
    return SUBSCRIPTION_LIMITS.get(plan, SUBSCRIPTION_LIMITS[SubscriptionPlan.BASIC])


def get_remaining_paper_upload_slots(db: Session, user: CurrentUser) -> int:
    """
    Return the number of papers the user can still upload under their plan.

    Returns 0 when at or over limit. All current plans have a finite paper
    upload limit, so there is no unlimited case to special-case.
    """
    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)
    paper_limit = limits[PAPER_UPLOAD_KEY]
    current_paper_count = paper_crud.get_total_paper_count(db=db, user=user)
    return max(0, int(paper_limit) - current_paper_count)


def get_user_knowledge_base_size(db: Session, user: CurrentUser) -> int:
    """
    Get the total size of the user's knowledge base in MB.
    """
    return paper_crud.get_size_of_knowledge_base(db, user=user)


def can_user_upload_paper(db: Session, user: CurrentUser) -> tuple[bool, str | None]:
    """
    Check if a user can upload a new paper based on their subscription limits.

    Returns:
        Whether the action is allowed and an optional user-facing reason.
    """
    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)

    current_paper_count = paper_crud.get_total_paper_count(db=db, user=user)
    paper_limit = limits[PAPER_UPLOAD_KEY]

    # If the user has reached their paper upload limit
    if current_paper_count >= paper_limit:
        track_event(
            "action_blocked_limit_reached",
            user_id=str(user.id),
            properties={
                "current_paper_count": current_paper_count,
                "paper_limit": paper_limit,
                "type": "paper_uploads",
                "plan": plan.value,
            },
            db=db,
        )
        return (
            False,
            f"You have reached your paper upload limit ({paper_limit} papers) for the {PLAN_LABELS[plan]} plan. Please upgrade your subscription to upload more papers, or delete existing papers to free up space.",
        )

    return True, None


def can_user_add_papers_to_project(
    db: Session, user: CurrentUser, project_id: uuid.UUID, paper_count: int = 1
) -> tuple[bool, str | None]:
    """
    Check if `paper_count` more papers can be added to a project.

    The cap and quota plan belong to the project owner, never the collaborator
    performing the action.

    Returns:
        Whether the action is allowed and an optional user-facing reason.
    """
    access = get_project_access(db, project_id=project_id, user_id=user.id)
    if access is None:
        return False, "Project not found"
    if not access.can_manage_papers:
        return False, "You do not have permission to add papers to this project"
    project = access.project
    owner = db.get(AuthUser, project.owner_id)
    if owner is None:
        raise RuntimeError(f"Project {project_id} has no owner")
    quota_user = CurrentUser.from_auth_user(owner)
    plan = get_user_subscription_plan(db, quota_user)
    limits = get_plan_limits(plan)
    project_paper_limit = limits[PROJECT_PAPERS_KEY]

    current_project_paper_count = project_paper_crud.get_paper_count_by_project_id(
        db, project_id=project_id, user=user
    )

    if current_project_paper_count + paper_count > project_paper_limit:
        track_event(
            "action_blocked_limit_reached",
            user_id=str(project.owner_id),
            properties={
                "current_project_paper_count": current_project_paper_count,
                "requested_paper_count": paper_count,
                "project_paper_limit": project_paper_limit,
                "type": "project_papers",
                "plan": plan.value,
            },
            db=db,
        )
        return (
            False,
            f"This project has reached its limit of {project_paper_limit} papers for the {PLAN_LABELS[plan]} plan. Please upgrade your subscription or remove papers from this project to add more.",
        )

    return True, None


def can_user_create_project(db: Session, user: CurrentUser) -> tuple[bool, str | None]:
    """
    Check if a user can create a new project based on their subscription limits.

    Returns:
        Whether the action is allowed and an optional user-facing reason.
    """
    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)

    current_project_count = int(
        db.scalar(select(func.count(Project.id)).where(Project.owner_id == user.id))
        or 0
    )
    project_limit = limits[PROJECTS_KEY]

    # If the user has reached their project limit
    if current_project_count >= project_limit:
        track_event(
            "action_blocked_limit_reached",
            user_id=str(user.id),
            properties={
                "current_project_count": current_project_count,
                "project_limit": project_limit,
                "type": "projects",
                "plan": plan.value,
            },
            db=db,
        )
        return (
            False,
            f"You have reached your project limit ({project_limit} projects) for the {PLAN_LABELS[plan]} plan. Please upgrade your subscription to create more projects.",
        )

    return True, None


def can_user_access_knowledge_base(
    db: Session, user: CurrentUser
) -> tuple[bool, str | None]:
    """
    Check if a user can access their knowledge base based on their subscription limits.

    Returns:
        Whether the action is allowed and an optional user-facing reason.
    """
    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)

    current_size_mb = get_user_knowledge_base_size(db, user)
    kb_limit = limits[KB_SIZE_KEY]

    # If the user has exceeded their knowledge base size limit
    if current_size_mb >= kb_limit:
        track_event(
            "action_blocked_limit_reached",
            user_id=str(user.id),
            properties={
                "current_size_mb": current_size_mb,
                "kb_limit": kb_limit,
                "type": "knowledge_base_size",
                "plan": plan.value,
            },
            db=db,
        )
        return (
            False,
            f"You have reached your knowledge base size limit ({kb_limit} KB) for the {PLAN_LABELS[plan]} plan. Please upgrade your subscription to access more data.",
        )

    return True, None


def can_user_auto_sync_zotero(db: Session, user: CurrentUser) -> bool:
    """Return True if the user's plan allows automatic Zotero sync (Researcher only)."""
    return get_user_subscription_plan(db, user) == SubscriptionPlan.RESEARCHER


def get_user_usage_info(db: Session, user: CurrentUser) -> dict[str, object]:
    """Return resource limits plus the current Monday-based Token Credit window."""
    from app.llm.token_credits import token_quota_status

    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)
    current_paper_count = paper_crud.get_total_paper_count(db=db, user=user)
    paper_limit = limits[PAPER_UPLOAD_KEY]
    total_size = paper_crud.get_size_of_knowledge_base(db, user=user)
    total_size_allowed = limits[KB_SIZE_KEY]
    current_project_count = int(
        db.scalar(select(func.count(Project.id)).where(Project.owner_id == user.id))
        or 0
    )
    project_limit = limits[PROJECTS_KEY]
    token_limit, token_used, token_remaining, token_overage = token_quota_status(
        db, user=user
    )

    return {
        "plan": plan.value,
        "limits": {**limits},
        "usage": {
            "paper_uploads": current_paper_count,
            "paper_uploads_remaining": max(0, int(paper_limit) - current_paper_count),
            "knowledge_base_size": total_size,
            "knowledge_base_size_remaining": max(
                0, int(total_size_allowed) - total_size
            ),
            "token_credits_weekly": token_limit,
            "token_credits_used": token_used,
            "token_credits_remaining": token_remaining,
            "token_credits_overage": token_overage,
            "projects": current_project_count,
            "projects_remaining": max(0, int(project_limit) - current_project_count),
        },
    }
