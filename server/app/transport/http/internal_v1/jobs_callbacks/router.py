"""Authenticated router composition for Jobs callbacks."""

from app.helpers.jobs_webhooks import verify_jobs_webhook
from fastapi import APIRouter, Depends

from .lifecycle import lifecycle_webhook_router
from .terminal import terminal_router

webhook_router = APIRouter(dependencies=[Depends(verify_jobs_webhook)])
webhook_router.include_router(lifecycle_webhook_router)
webhook_router.include_router(terminal_router)

__all__ = ["webhook_router"]
