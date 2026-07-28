"""Authenticated router composition for Jobs callbacks."""

from app.helpers.jobs_webhooks import verify_jobs_webhook
from fastapi import APIRouter, Depends

from .documents import (
    document_webhook_router,
    handle_paper_parser_upgrade_webhook,
)
from .lifecycle import lifecycle_webhook_router
from .research import research_webhook_router

webhook_router = APIRouter(dependencies=[Depends(verify_jobs_webhook)])
webhook_router.include_router(lifecycle_webhook_router)
webhook_router.include_router(research_webhook_router)
webhook_router.include_router(document_webhook_router)

__all__ = ["handle_paper_parser_upgrade_webhook", "webhook_router"]
