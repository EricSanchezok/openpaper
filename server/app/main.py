import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from app.api.api import router
from app.api.auth_api import auth_router
from app.api.conversation_api import conversation_router
from app.api.documents import document_router, library_router, public_document_router
from app.api.message_api import message_router
from app.api.onboarding_api import onboarding_router
from app.api.paper_search_api import paper_search_router
from app.api.paper_tag_api import paper_tag_router
from app.api.paper_upload_api import paper_upload_router
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
from app.api.projects.project_papers_api import project_papers_router
from app.api.projects.projects_api import projects_router
from app.api.projects.projects_invitation_api import (
    router as projects_invitation_router,
)
from app.api.search_api import search_router
from app.api.subscription import subscription_router
from app.api.jobs_webhooks import webhook_router
from app.api.zotero_import_api import zotero_router
from app.auth.runtime import auth_lifespan, cloud_auth_router, cloud_user_router
from app.database.admin import setup_admin
from app.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
)
from app.services.job_dispatcher import run_job_dispatcher
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.database.database import get_db
from starlette.exceptions import HTTPException as StarletteHTTPException

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

load_dotenv()


@asynccontextmanager
async def app_lifespan(application: FastAPI) -> AsyncIterator[None]:
    stop_dispatcher = asyncio.Event()
    async with auth_lifespan(application):
        dispatcher = asyncio.create_task(
            run_job_dispatcher(stop_dispatcher),
            name="jobs-outbox-dispatcher",
        )
        try:
            yield
        finally:
            stop_dispatcher.set()
            await dispatcher


app = FastAPI(
    title="Scholens",
    description="A web application for uploading and annotating papers.",
    version="1.0.0",
    lifespan=app_lifespan,
    exception_handlers={
        AppError: app_error_handler,
        StarletteHTTPException: http_error_handler,
        Exception: unhandled_error_handler,
    },
)

client_domain = os.getenv("CLIENT_DOMAIN", "http://localhost:3000")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[client_domain],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    allow_credentials=True,
    max_age=600,  # Cache preflight requests for 10 minutes
)

# Include the router in the main app
app.include_router(router, prefix="/api")
app.include_router(cloud_auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(cloud_user_router, prefix="/api/user", tags=["user"])
app.include_router(auth_router, prefix="/api/auth")
app.include_router(conversation_router, prefix="/api/conversations")
app.include_router(library_router, prefix="/api/library")
app.include_router(document_router, prefix="/api/documents")
app.include_router(public_document_router, prefix="/api/public")
app.include_router(message_router, prefix="/api/message")
app.include_router(projects_router, prefix="/api/projects")
app.include_router(project_papers_router, prefix="/api/projects")
app.include_router(projects_invitation_router, prefix="/api")
app.include_router(paper_search_router, prefix="/api/search/global")
app.include_router(search_router, prefix="/api/search/local")
app.include_router(paper_upload_router, prefix="/api/paper/upload")
app.include_router(document_research_router, prefix="/api/documents")
app.include_router(project_research_router, prefix="/api/projects")
app.include_router(research_router, prefix="/api")
app.include_router(document_generation_router, prefix="/api/documents")
app.include_router(project_generation_router, prefix="/api/projects")
app.include_router(jobs_router, prefix="/api/jobs")
app.include_router(paper_tag_router, prefix="/api/paper/tag")
app.include_router(
    subscription_router, prefix="/api/subscription"
)  # Subscription routes
app.include_router(webhook_router, prefix="/api/webhooks")  # Webhook routes
app.include_router(onboarding_router, prefix="/api/onboarding")
app.include_router(zotero_router, prefix="/api/zotero")


@app.get("/livez", include_in_schema=False)
def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz(db: Session = Depends(get_db)) -> dict[str, str]:
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


setup_admin(app)  # Setup admin interface

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = (
        "%(asctime)s - %(levelname)s - %(message)s"
    )
    log_config["formatters"]["default"]["fmt"] = (
        "%(asctime)s - %(levelname)s - %(message)s"
    )
    # Set higher log level to see more details
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        # reload=True,
        log_level="debug",
        log_config=log_config,
        forwarded_allow_ips="*",  # Allow all forwarded IPs
        proxy_headers=True,  # Enable proxy headers
    )
