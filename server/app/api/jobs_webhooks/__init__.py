"""Signed callbacks from the Scholens Jobs service."""

from app.api.jobs_webhooks.router import webhook_router

__all__ = ["webhook_router"]
