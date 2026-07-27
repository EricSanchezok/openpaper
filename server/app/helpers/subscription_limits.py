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


def lock_account_resource_quota(db: Session, *, user_id: int) -> None:
    """Serialize resource grants for one account within the current transaction."""
    db.execute(select(func.pg_advisory_xact_lock(user_id)))


def get_quota_user(db: Session, *, user_id: int) -> CurrentUser:
    user = db.get(AuthUser, user_id)
    if user is None:
        raise AppError(
            code="quota_owner_not_found",
            message="The account that owns this resource no longer exists",
            status_code=409,
        )
    return CurrentUser.from_auth_user(user)


def _require_incremental_account_capacity(
    db: Session,
    *,
    owner_id: int,
    documents: list[Document],
) -> None:
    """Validate only documents that are newly billable to an account."""
    if not documents:
        return

    unknown_size = next(
        (document for document in documents if document.size_in_kb is None),
        None,
    )
    if unknown_size is not None:
        raise AppError(
            code="document_not_ready",
            message="A document is still being processed",
            status_code=409,
        )

    owner = get_quota_user(db, user_id=owner_id)
    plan = get_user_subscription_plan(db, owner)
    limits = get_plan_limits(plan)
    current_count = paper_crud.get_total_paper_count(db=db, user=owner)
    if current_count + len(documents) > limits[PAPER_UPLOAD_KEY]:
        raise AppError(
            code="paper_quota_exceeded",
            message="The account's paper limit would be exceeded",
            status_code=403,
        )

    if paper_crud.has_unknown_billed_document_size(db, user_id=owner_id):
        raise AppError(
            code="storage_usage_unavailable",
            message="Storage usage is still being reconciled",
            status_code=409,
        )
    current_size = paper_crud.get_size_of_knowledge_base(db, user=owner)
    added_size = sum(document.size_in_kb or 0 for document in documents)
    if current_size + added_size > limits[KB_SIZE_KEY]:
        raise AppError(
            code="storage_quota_exceeded",
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

    newly_billed = list(
        db.scalars(
            select(Document).where(
                Document.id.in_([document.id for document in documents]),
                ~paper_crud.is_billed_to(owner_id),
            )
        ).all()
    )
    _require_incremental_account_capacity(
        db,
        owner_id=owner_id,
        documents=newly_billed,
    )


def require_library_document_capacity(
    db: Session,
    *,
    user: CurrentUser,
    document: Document,
) -> None:
    """Validate the incremental cost of collecting one shared document."""
    lock_account_resource_quota(db, user_id=user.id)
    already_billed = db.scalar(
        select(Document.id).where(
            Document.id == document.id,
            paper_crud.is_billed_to(user.id),
        )
    )
    _require_incremental_account_capacity(
        db,
        owner_id=user.id,
        documents=[] if already_billed is not None else [document],
    )


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
