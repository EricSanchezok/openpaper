"""FastAPI composition root.

Routers are assembled only here so versioning and trust boundaries cannot be
silently changed by individual business modules.
"""

from __future__ import annotations

import logging

from app.transport.http.public_v1.auth import (
    admin_router,
    topics_router,
)
from app.transport.http.public_v1.conversations import conversation_router
from app.transport.http.public_v1.document_uploads import document_upload_router
from app.transport.http.public_v1.documents import (
    document_router,
    library_router,
    public_document_router,
)
from app.transport.http.internal_v1.jobs_callbacks import (
    webhook_router as jobs_callback_router,
)
from app.transport.http.public_v1.library_tags import library_tags_router
from app.transport.http.public_v1.messages import message_router
from app.transport.http.public_v1.discovery import (
    author_discovery_router,
    paper_search_router,
)
from app.transport.http.public_v1.projects.documents import (
    library_project_papers_router,
    paper_projects_router,
    project_papers_router,
)
from app.transport.http.public_v1.projects.projects import projects_router
from app.transport.http.public_v1.projects.invitations import (
    router as projects_invitation_router,
)
from app.transport.http.public_v1.research import (
    document_research_router,
    project_research_router,
    research_router,
)
from app.transport.http.public_v1.research_generation import (
    document_generation_router,
    jobs_router,
    project_generation_router,
)
from app.transport.http.public_v1.paper_search import search_router
from app.transport.http.public_v1.research_search import research_search_router
from app.transport.http.public_v1.billing import subscription_router
from app.transport.http.webhooks_v1.stripe import router as stripe_webhook_router
from app.transport.http.public_v1.zotero import zotero_oauth_router, zotero_router
from app.modules.identity.infrastructure.cloud_auth import (
    cloud_auth_router,
    cloud_user_router,
)
from app.bootstrap.lifespan import app_lifespan
from app.bootstrap.execution import (
    create_application_executor,
    create_conversation_agent_runtime,
    create_conversation_chat,
    create_job_completion_processor,
    create_onboarding_finisher,
    create_paper_ingestion_workflow,
    create_research_generation_workflow,
    create_stripe_webhook_processor,
    create_workspace_tooling,
    create_zotero_workflow,
)
from app.bootstrap.settings import (
    INTERNAL_API_PREFIX,
    PUBLIC_API_PREFIX,
    WEBHOOK_API_PREFIX,
    AppSettings,
)
from app.database.admin import setup_admin
from app.database.database import SessionLocal
from app.shared.domain import AppError
from app.transport.http.errors import (
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
)
from app.transport.http.public_v1.identity import router as identity_router
from app.transport.http.public_v1.onboarding import onboarding_router
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _public_router() -> APIRouter:
    router = APIRouter()
    router.include_router(identity_router)
    router.include_router(cloud_auth_router, prefix="/auth", tags=["auth"])
    router.include_router(cloud_user_router, prefix="/me", tags=["user"])
    router.include_router(topics_router, prefix="/discovery")
    router.include_router(admin_router, prefix="/admin")
    router.include_router(
        zotero_oauth_router,
        prefix="/integrations/zotero/oauth",
        tags=["zotero"],
    )
    # Static chat capability routes must precede the UUID conversation route.
    router.include_router(message_router, prefix="/conversations")
    router.include_router(conversation_router, prefix="/conversations")
    router.include_router(library_router, prefix="/library")
    router.include_router(library_project_papers_router, prefix="/library")
    router.include_router(library_tags_router, prefix="/library")
    router.include_router(document_router, prefix="/papers")
    router.include_router(paper_projects_router, prefix="/papers")
    router.include_router(public_document_router, prefix="/shares")
    router.include_router(projects_router, prefix="/projects")
    router.include_router(project_papers_router, prefix="/projects")
    router.include_router(projects_invitation_router)
    router.include_router(paper_search_router, prefix="/discovery/papers")
    router.include_router(author_discovery_router, prefix="/discovery")
    router.include_router(search_router, prefix="/search/papers")
    router.include_router(research_search_router, prefix="/search/research")
    router.include_router(document_upload_router, prefix="/paper-ingestions")
    router.include_router(document_research_router, prefix="/papers")
    router.include_router(project_research_router, prefix="/projects")
    router.include_router(research_router)
    router.include_router(document_generation_router, prefix="/papers")
    router.include_router(project_generation_router, prefix="/projects")
    router.include_router(jobs_router, prefix="/jobs")
    router.include_router(subscription_router, prefix="/billing")
    router.include_router(onboarding_router, prefix="/me/onboarding")
    router.include_router(zotero_router, prefix="/integrations/zotero")
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
    application.state.settings = runtime_settings
    executor = create_application_executor(runtime_settings)
    application.state.application_executor = executor
    ingestion_workflow = create_paper_ingestion_workflow(executor)
    tool_catalog, tool_dispatcher = create_workspace_tooling(
        executor=executor,
        ingestion=ingestion_workflow,
    )
    conversation_runtime = create_conversation_agent_runtime(
        catalog=tool_catalog,
        dispatcher=tool_dispatcher,
    )
    application.state.tool_catalog = tool_catalog
    application.state.tool_dispatcher = tool_dispatcher
    application.state.conversation_agent_runtime = conversation_runtime
    application.state.conversation_chat = create_conversation_chat(
        executor,
        conversation_runtime,
    )
    application.state.onboarding_finisher = create_onboarding_finisher()
    application.state.stripe_webhook_processor = create_stripe_webhook_processor()
    application.state.paper_ingestion_workflow = ingestion_workflow
    application.state.research_generation_workflow = (
        create_research_generation_workflow(executor)
    )
    application.state.zotero_workflow = create_zotero_workflow(executor)
    application.state.job_completion_processor = create_job_completion_processor()
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
    def readyz() -> dict[str, str]:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return {"status": "ready"}

    setup_admin(application)
    return application
