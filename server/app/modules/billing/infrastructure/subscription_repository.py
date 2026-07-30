from datetime import datetime
from typing import Any

from app.database.models import Subscription, SubscriptionStatus
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


class SubscriptionRepository:
    """Persistence operations for subscription management."""

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
            db.flush()
            db.refresh(subscription)
            return subscription

        # Create new subscription
        create_data = SubscriptionCreate(user_id=user_id, **subscription_data)
        created = Subscription(**create_data.model_dump())
        db.add(created)
        db.flush()
        db.refresh(created)
        return created


subscription_repository = SubscriptionRepository()
