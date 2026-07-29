"""FastAPI composition root.

Routers are assembled only here so versioning and trust boundaries cannot be
silently changed by individual business modules.
"""

from __future__ import annotations

import logging

from app.api.auth_api import auth_router
from app.api.conversation_api import conversation_router
from app.api.document_upload_api import document_upload_router
from app.api.documents import document_router, library_router, public_document_router
from app.api.jobs_webhooks import webhook_router as jobs_callback_router
from app.api.library_tags_api import library_tags_router
from app.api.message_api import message_router
from app.api.paper_search_api import paper_search_router
from app.api.projects.project_papers_api import project_papers_router
from app.api.projects.projects_api import projects_router
from app.api.projects.projects_invitation_api import (
    router as projects_invitation_router,
)
from app.api.research_api import (
    document_research_router,
    project_research_router,
    research_router,
)
from app.api.research_generation_api import (
    document_generation_router,
    jobs_router,
    project_generation_router,
)
from app.api.search_api import search_router
from app.api.subscription import subscription_router
from app.api.subscription.webhook import router as stripe_webhook_router
from app.api.zotero_import_api import zotero_router
from app.modules.identity.infrastructure.cloud_auth import (
    cloud_auth_router,
    cloud_user_router,
)
from app.bootstrap.lifespan import app_lifespan
from app.bootstrap.settings import (
    INTERNAL_API_PREFIX,
    PUBLIC_API_PREFIX,
    WEBHOOK_API_PREFIX,
    AppSettings,
)
from app.database.admin import setup_admin
from app.database.database import get_db
from app.shared.domain import AppError
from app.transport.http.errors import (
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
)
from app.transport.http.public_v1.identity import router as identity_router
from app.transport.http.public_v1.onboarding import onboarding_router
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _public_router() -> APIRouter:
    router = APIRouter()
    router.include_router(identity_router)
    router.include_router(cloud_auth_router, prefix="/auth", tags=["auth"])
    router.include_router(cloud_user_router, prefix="/me", tags=["user"])
    router.include_router(auth_router, prefix="/auth")
    router.include_router(conversation_router, prefix="/conversations")
    router.include_router(library_router, prefix="/library")
    router.include_router(library_tags_router, prefix="/library")
    router.include_router(document_router, prefix="/documents")
    router.include_router(public_document_router, prefix="/public")
    router.include_router(message_router, prefix="/message")
    router.include_router(projects_router, prefix="/projects")
    router.include_router(project_papers_router, prefix="/projects")
    router.include_router(projects_invitation_router)
    router.include_router(paper_search_router, prefix="/search/global")
    router.include_router(search_router, prefix="/search/local")
    router.include_router(document_upload_router, prefix="/documents/uploads")
    router.include_router(document_research_router, prefix="/documents")
    router.include_router(project_research_router, prefix="/projects")
    router.include_router(research_router)
    router.include_router(document_generation_router, prefix="/documents")
    router.include_router(project_generation_router, prefix="/projects")
    router.include_router(jobs_router, prefix="/jobs")
    router.include_router(subscription_router, prefix="/subscription")
    router.include_router(onboarding_router, prefix="/me/onboarding")
    router.include_router(zotero_router, prefix="/zotero")
    return router


def create_app(settings: AppSettings | None = None) -> FastAPI:
    runtime_settings = settings or AppSettings()
    application = FastAPI(
        title="Scholens",
        description="Scholens public application API.",
        version="1.0.0",
        lifespan=app_lifespan,
        exception_handlers={
            AppError: app_error_handler,
            StarletteHTTPException: http_error_handler,
            Exception: unhandled_error_handler,
        },
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[runtime_settings.client_domain],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        allow_headers=["*"],
        expose_headers=["*"],
        allow_credentials=True,
        max_age=600,
    )
    application.include_router(
        _public_router(),
        prefix=PUBLIC_API_PREFIX,
    )
    application.include_router(
        stripe_webhook_router,
        prefix=WEBHOOK_API_PREFIX,
        tags=["webhooks"],
    )
    application.include_router(
        jobs_callback_router,
        prefix=INTERNAL_API_PREFIX,
        include_in_schema=False,
    )

    @application.get("/livez", include_in_schema=False)
    def livez() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz", include_in_schema=False)
    def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}

    setup_admin(application)
    return application
