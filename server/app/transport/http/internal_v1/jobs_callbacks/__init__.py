"""Signed callbacks from the Scholens Jobs service."""

from app.transport.http.internal_v1.jobs_callbacks.router import webhook_router

__all__ = ["webhook_router"]
