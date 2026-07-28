from datetime import datetime, timezone
from typing import Any

from app.database.models import Subscription, SubscriptionPlan, SubscriptionStatus
from app.schemas.user import CurrentUser
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session


class SubscriptionCreate(BaseModel):
    """Schema for creating a subscription"""

    user_id: int
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    stripe_schedule_id: str | None = None
    status: str = SubscriptionStatus.INCOMPLETE.value
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


class SubscriptionUpdate(BaseModel):
    """Schema for updating a subscription"""

    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_price_id: str | None = None
    stripe_schedule_id: str | None = None
    status: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None


class CRUDSubscription:
    """CRUD operations for subscription management"""

    def is_user_active(self, db: Session, user: CurrentUser) -> bool:
        """Check if the user has an active subscription"""
        return self.is_user_id_active(db, user.id)

    def is_user_id_active(self, db: Session, user_id: int) -> bool:
        subscription = self.get_by_user_id(db, user_id)
        if not subscription or not subscription.current_period_end:
            return False
        # User is active if `current_period_end` is in the future
        return subscription.current_period_end > datetime.now(tz=timezone.utc)

    def get_by_user_id(self, db: Session, user_id: int) -> Subscription | None:
        """Get subscription by user_id"""
        return db.scalars(
            select(Subscription).where(Subscription.user_id == user_id)
        ).first()

    def get_by_stripe_subscription_id(
        self, db: Session, subscription_id: str
    ) -> Subscription | None:
        """Get subscription by stripe_subscription_id"""
        return db.scalars(
            select(Subscription).where(
                Subscription.stripe_subscription_id == subscription_id
            )
        ).first()

    def get_by_stripe_customer_id(
        self, db: Session, customer_id: str
    ) -> Subscription | None:
        """Get subscription by stripe_customer_id"""
        return db.scalars(
            select(Subscription).where(Subscription.stripe_customer_id == customer_id)
        ).first()

    def create_or_update(
        self, db: Session, user_id: int, subscription_data: dict[str, Any]
    ) -> Subscription:
        """Create a subscription or update if exists"""
        subscription = self.get_by_user_id(db, user_id)

        if subscription:
            # Update existing subscription
            for key, value in subscription_data.items():
                setattr(subscription, key, value)
            db.commit()
            db.refresh(subscription)
            return subscription

        # Create new subscription
        create_data = SubscriptionCreate(user_id=user_id, **subscription_data)
        created = Subscription(**create_data.model_dump())
        db.add(created)
        db.commit()
        db.refresh(created)
        return created

    def update_subscription_status(
        self,
        db: Session,
        subscription_id: str,
        status: str,
        stripe_price_id: str | None = None,
        plan: SubscriptionPlan | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        cancel_at_period_end: bool | None = None,
    ) -> Subscription | None:
        """Update subscription status and period dates"""
        subscription = self.get_by_stripe_subscription_id(db, subscription_id)
        if not subscription:
            return None

        # Use setattr to update fields
        setattr(subscription, "status", status)
        if plan:
            setattr(subscription, "plan", plan)

        if stripe_price_id:
            setattr(subscription, "stripe_price_id", stripe_price_id)

        # Update period dates if provided
        if period_start:
            setattr(subscription, "current_period_start", period_start)

        if period_end:
            setattr(subscription, "current_period_end", period_end)

        if cancel_at_period_end is not None:
            setattr(subscription, "cancel_at_period_end", cancel_at_period_end)

        db.commit()
        db.refresh(subscription)
        return subscription


subscription_crud = CRUDSubscription()
