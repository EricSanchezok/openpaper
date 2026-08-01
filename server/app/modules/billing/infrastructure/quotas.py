"""Subscription plans and atomic resource-quota enforcement."""

import logging
import uuid
from datetime import datetime, timezone

from app.modules.billing.infrastructure.usage_repository import (
    resource_usage_repository,
)
from app.modules.billing.infrastructure.subscription_repository import (
    subscription_repository,
)
from app.modules.billing.domain import (
    AccountCapacityFacts,
    SubscriptionFacts,
    effective_plan,
    entitlements_for,
    paper_upload_denial,
    project_creation_denial,
    remaining,
    require_account_document_capacity,
    require_project_paper_capacity,
)
from app.database.models import (
    AuthUser,
    Document,
    Project,
    ProjectPaper,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.database.product_analytics import track_event
from app.shared.domain import AppError, FailureKind
from app.shared.application import Actor
from sqlalchemy import func, select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_user_subscription_plan(db: Session, user: Actor) -> SubscriptionPlan:
    """
    Get the user's current subscription plan.
    Returns BASIC if no active subscription is found.
    """
    subscription = subscription_repository.get_by_user_id(db, user.id)

    facts = (
        SubscriptionFacts(
            plan=SubscriptionPlan(subscription.plan),
            status=SubscriptionStatus(subscription.status),
            current_period_end=subscription.current_period_end,
        )
        if subscription is not None
        else None
    )
    return effective_plan(facts, now=datetime.now(timezone.utc))


def get_plan_limits(plan: SubscriptionPlan) -> dict[str, int]:
    """Get the limits for a specific subscription plan."""
    return entitlements_for(plan).as_limits()


def lock_account_resource_quota(db: Session, *, user_id: int) -> None:
    """Serialize resource grants for one account within the current transaction."""
    db.execute(select(func.pg_advisory_xact_lock(user_id)))


def get_quota_user(db: Session, *, user_id: int) -> Actor:
    user = db.get(AuthUser, user_id)
    if user is None:
        raise AppError(
            code="quota_owner_not_found",
            message="The account that owns this resource no longer exists",
            kind=FailureKind.CONFLICT,
        )
    profile = user.profile
    return Actor.from_identity_projection(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        status=str(user.status),
        email_verified=user.email_verified_at is not None,
        locale=profile.locale if profile else None,
        is_admin=profile.is_admin if profile else False,
        is_blocked=profile.is_blocked if profile else False,
    )


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
    current_count = resource_usage_repository.completed_reference_count(
        db, user_id=owner.id
    )
    current_size = resource_usage_repository.completed_storage_kb(db, user_id=owner.id)
    added_size = sum((document.size_bytes + 1023) // 1024 for document in documents)
    require_account_document_capacity(
        plan,
        AccountCapacityFacts(
            current_documents=current_count,
            current_storage_kb=current_size,
            added_documents=len(documents),
            added_storage_kb=added_size,
            project_owner=project_owner,
        ),
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
    current_project_count = int(
        db.scalar(
            select(func.count(ProjectPaper.id)).where(
                ProjectPaper.project_id == project_id
            )
        )
        or 0
    )
    require_project_paper_capacity(
        plan,
        current_documents=current_project_count,
        added_documents=len(documents),
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
    paper_limit = entitlements_for(plan).paper_uploads
    current_paper_count = resource_usage_repository.completed_reference_count(
        db, user_id=user.id
    )
    return remaining(paper_limit, current_paper_count)


def can_user_upload_paper(db: Session, user: Actor) -> tuple[bool, str | None]:
    """
    Check if a user can upload a new paper based on their subscription limits.

    Returns:
        Whether the action is allowed and an optional user-facing reason.
    """
    plan = get_user_subscription_plan(db, user)
    current_paper_count = resource_usage_repository.completed_reference_count(
        db, user_id=user.id
    )
    denial = paper_upload_denial(plan, current_documents=current_paper_count)
    if denial is not None:
        paper_limit = entitlements_for(plan).paper_uploads
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
            denial,
        )

    return True, None


def can_user_create_project(db: Session, user: Actor) -> tuple[bool, str | None]:
    """
    Check if a user can create a new project based on their subscription limits.

    Returns:
        Whether the action is allowed and an optional user-facing reason.
    """
    plan = get_user_subscription_plan(db, user)
    current_project_count = int(
        db.scalar(select(func.count(Project.id)).where(Project.owner_id == user.id))
        or 0
    )
    denial = project_creation_denial(plan, current_projects=current_project_count)
    if denial is not None:
        project_limit = entitlements_for(plan).projects
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
            denial,
        )

    return True, None


def can_user_auto_sync_zotero(db: Session, user: Actor) -> bool:
    """Return True if the user's plan allows automatic Zotero sync (Researcher only)."""
    return entitlements_for(get_user_subscription_plan(db, user)).zotero_auto_sync


def get_user_usage_info(db: Session, user: Actor) -> dict[str, object]:
    """Return resource limits plus the current Monday-based Token Credit window."""
    from app.llm.token_credits import token_quota_status

    plan = get_user_subscription_plan(db, user)
    limits = entitlements_for(plan)
    current_paper_count = resource_usage_repository.completed_reference_count(
        db, user_id=user.id
    )
    paper_limit = limits.paper_uploads
    total_size = resource_usage_repository.completed_storage_kb(db, user_id=user.id)
    total_size_allowed = limits.knowledge_base_size_kb
    current_project_count = int(
        db.scalar(select(func.count(Project.id)).where(Project.owner_id == user.id))
        or 0
    )
    project_limit = limits.projects
    token_limit, token_used, token_remaining, token_overage = token_quota_status(
        db, user=user
    )

    return {
        "plan": plan.value,
        "limits": limits.as_limits(),
        "usage": {
            "paper_uploads": current_paper_count,
            "paper_uploads_remaining": remaining(
                paper_limit,
                current_paper_count,
            ),
            "knowledge_base_size": total_size,
            "knowledge_base_size_remaining": remaining(
                total_size_allowed,
                total_size,
            ),
            "token_credits_weekly": token_limit,
            "token_credits_used": token_used,
            "token_credits_remaining": token_remaining,
            "token_credits_overage": token_overage,
            "projects": current_project_count,
            "projects_remaining": remaining(project_limit, current_project_count),
        },
    }
