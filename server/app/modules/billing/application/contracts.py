from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class SubscriptionInterval(StrEnum):
    MONTHLY = "month"
    YEARLY = "year"


class CheckoutSessionResponse(BaseModel):
    client_secret: str | None


class CheckoutSessionStatusResponse(BaseModel):
    status: str
    customer_email: str | None = None
    backend_subscription_found: bool = False
    backend_subscription_status: str | None = None


class PortalSessionResponse(BaseModel):
    url: str


class SubscriptionSummary(BaseModel):
    status: str
    interval: SubscriptionInterval | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool


class ScheduledIntervalChange(BaseModel):
    new_interval: SubscriptionInterval
    effective_date: datetime | None


class SubscriptionResponse(BaseModel):
    has_subscription: bool
    had_subscription: bool = False
    requires_payment_update: bool = False
    subscription: SubscriptionSummary | None = None
    scheduled_change: ScheduledIntervalChange | None = None


class SubscriptionActionResponse(BaseModel):
    success: bool
    error: str | None = None
    message: str | None = None
    redirect_to_checkout: bool = False
    subscription_id: str | None = None
    action: str | None = None


class IntervalChangeResponse(BaseModel):
    success: bool
    error: str | None = None
    message: str | None = None
    scheduled_date: datetime | None = None
    new_interval: SubscriptionInterval | None = None


class SubscriptionLimits(BaseModel):
    paper_uploads: int
    knowledge_base_size: int
    token_credits_weekly: int
    projects: int
    project_papers: int


class SubscriptionUsage(BaseModel):
    paper_uploads: int
    paper_uploads_remaining: int
    knowledge_base_size: int
    knowledge_base_size_remaining: int
    token_credits_weekly: int
    token_credits_used: int
    token_credits_remaining: int
    token_credits_overage: int
    projects: int
    projects_remaining: int


class UsageResponse(BaseModel):
    plan: str
    limits: SubscriptionLimits
    usage: SubscriptionUsage
