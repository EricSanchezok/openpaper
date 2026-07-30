"""Router composition for signed Jobs callbacks."""

from fastapi import APIRouter

from .lifecycle import lifecycle_webhook_router
from .terminal import terminal_router

webhook_router = APIRouter()
webhook_router.include_router(lifecycle_webhook_router)
webhook_router.include_router(terminal_router)

__all__ = ["webhook_router"]
