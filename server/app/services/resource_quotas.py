"""Subscription plans and atomic resource-quota enforcement."""

import logging
import uuid
from datetime import datetime, timezone

from app.modules.billing.infrastructure.usage_repository import (
    resource_usage_repository,
)
from app.database.crud.subscription_crud import subscription_crud
from app.database.models import (
    AuthUser,
    Document,
    Project,
    ProjectPaper,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.database.telemetry import track_event
from app.errors import AppError
from app.shared.application import Actor
from app.modules.identity.infrastructure.users import actor_from_auth_user
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


def get_user_subscription_plan(db: Session, user: Actor) -> SubscriptionPlan:
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


def lock_account_resource_quota(db: Session, *, user_id: int) -> None:
    """Serialize resource grants for one account within the current transaction."""
    db.execute(select(func.pg_advisory_xact_lock(user_id)))


def get_quota_user(db: Session, *, user_id: int) -> Actor:
    user = db.get(AuthUser, user_id)
    if user is None:
        raise AppError(
            code="quota_owner_not_found",
            message="The account that owns this resource no longer exists",
            status_code=409,
        )
    return actor_from_auth_user(user)


def _require_incremental_account_capacity(
    db: Session,
    *,
    owner_id: int,
    documents: list[Document],
    project_owner: bool = False,
) -> None:
    """Validate the logical references that will be newly billed."""
    if not documents:
        return

    owner = get_quota_user(db, user_id=owner_id)
    plan = get_user_subscription_plan(db, owner)
    limits = get_plan_limits(plan)
    current_count = resource_usage_repository.completed_reference_count(
        db, user_id=owner.id
    )
    if current_count + len(documents) > limits[PAPER_UPLOAD_KEY]:
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if project_owner
                else "paper_quota_exceeded"
            ),
            message="The account's paper limit would be exceeded",
            status_code=403,
        )

    current_size = resource_usage_repository.completed_storage_kb(db, user_id=owner.id)
    added_size = sum((document.size_bytes + 1023) // 1024 for document in documents)
    if current_size + added_size > limits[KB_SIZE_KEY]:
        raise AppError(
            code=(
                "project_owner_quota_exceeded"
                if project_owner
                else "storage_quota_exceeded"
            ),
            message="The account's storage limit would be exceeded",
            status_code=403,
        )


def require_project_document_capacity(
    db: Session,
    *,
    owner_id: int,
    project_id: uuid.UUID,
    documents: list[Document],
) -> None:
    """Validate Project and owner quotas for a set of new associations."""
    if not documents:
        return
    lock_account_resource_quota(db, user_id=owner_id)
    owner = get_quota_user(db, user_id=owner_id)
    plan = get_user_subscription_plan(db, owner)
    limits = get_plan_limits(plan)

    current_project_count = int(
        db.scalar(
            select(func.count(ProjectPaper.id)).where(
                ProjectPaper.project_id == project_id
            )
        )
        or 0
    )
    if current_project_count + len(documents) > limits[PROJECT_PAPERS_KEY]:
        raise AppError(
            code="project_paper_quota_exceeded",
            message="The Project's paper limit would be exceeded",
            status_code=403,
        )

    _require_incremental_account_capacity(
        db,
        owner_id=owner_id,
        documents=documents,
        project_owner=True,
    )


def require_library_document_capacity(
    db: Session,
    *,
    user: Actor,
    document: Document,
) -> None:
    """Validate the incremental cost of collecting one shared document."""
    lock_account_resource_quota(db, user_id=user.id)
    _require_incremental_account_capacity(
        db,
        owner_id=user.id,
        documents=[document],
    )


def get_remaining_paper_upload_slots(db: Session, user: Actor) -> int:
    """
    Return the number of papers the user can still upload under their plan.

    Returns 0 when at or over limit. All current plans have a finite paper
    upload limit, so there is no unlimited case to special-case.
    """
    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)
    paper_limit = limits[PAPER_UPLOAD_KEY]
    current_paper_count = resource_usage_repository.completed_reference_count(
        db, user_id=user.id
    )
    return max(0, int(paper_limit) - current_paper_count)


def can_user_upload_paper(db: Session, user: Actor) -> tuple[bool, str | None]:
    """
    Check if a user can upload a new paper based on their subscription limits.

    Returns:
        Whether the action is allowed and an optional user-facing reason.
    """
    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)

    current_paper_count = resource_usage_repository.completed_reference_count(
        db, user_id=user.id
    )
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


def can_user_create_project(db: Session, user: Actor) -> tuple[bool, str | None]:
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


def can_user_auto_sync_zotero(db: Session, user: Actor) -> bool:
    """Return True if the user's plan allows automatic Zotero sync (Researcher only)."""
    return get_user_subscription_plan(db, user) == SubscriptionPlan.RESEARCHER


def get_user_usage_info(db: Session, user: Actor) -> dict[str, object]:
    """Return resource limits plus the current Monday-based Token Credit window."""
    from app.llm.token_credits import token_quota_status

    plan = get_user_subscription_plan(db, user)
    limits = get_plan_limits(plan)
    current_paper_count = resource_usage_repository.completed_reference_count(
        db, user_id=user.id
    )
    paper_limit = limits[PAPER_UPLOAD_KEY]
    total_size = resource_usage_repository.completed_storage_kb(db, user_id=user.id)
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
