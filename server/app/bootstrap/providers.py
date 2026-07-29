"""Explicit infrastructure selection for replaceable application ports."""

from __future__ import annotations

from typing import Literal

from app.modules.papers.application.search import PaperSearchPort
from app.modules.papers.application.content import PaperContentCapabilities
from app.modules.papers.infrastructure.content_gateway import (
    SqlAlchemyPaperContentGateway,
)
from app.modules.papers.application.downloads import GetPaperDownload
from app.modules.papers.infrastructure.downloads import S3PaperDownloadSigner
from app.helpers.s3 import DEFAULT_SIGNED_URL_TTL_SECONDS
from app.modules.papers.application.ingestion import IngestPaper
from app.modules.papers.infrastructure.ingestion import (
    DefaultPaperIngestionLimits,
    DefaultPdfInputValidator,
    SafePdfUrlSource,
    SqlPaperIngestionGateway,
)
from app.modules.papers.infrastructure.knowledge_search import PostgresPaperSearch
from app.modules.projects.application.document_visibility import (
    ListAccessibleProjectDocuments,
)
from app.modules.projects.infrastructure.document_visibility import (
    SqlProjectDocumentVisibility,
)
from app.modules.research.application.search import (
    SearchResearch,
    build_research_search_cursor,
)
from app.modules.research.infrastructure.search import SqlResearchSearch
from app.modules.identity.application.onboarding import CompleteOnboarding
from app.modules.identity.infrastructure.onboarding_adapters import (
    CloudAuthDisplayNameWriter,
    EmailOnboardingNotifier,
    PostHogOnboardingEventRecorder,
    SqlAlchemyOnboardingWriter,
)
from app.modules.billing.application.webhooks import ProcessStripeWebhook
from app.modules.billing.infrastructure.webhook_adapter import StripeWebhookAdapter
from sqlalchemy.orm import Session


def build_paper_search(
    *,
    backend: Literal["postgres_fts"],
    db: Session,
) -> PaperSearchPort:
    if backend == "postgres_fts":
        return PostgresPaperSearch(db)
    raise ValueError(f"Unsupported paper search backend: {backend}")


def build_project_document_visibility(
    *,
    db: Session,
) -> ListAccessibleProjectDocuments:
    return ListAccessibleProjectDocuments(SqlProjectDocumentVisibility(db))


def build_paper_content(*, db: Session) -> PaperContentCapabilities:
    return PaperContentCapabilities(
        SqlAlchemyPaperContentGateway(db),
        build_project_document_visibility(db=db),
    )


def build_paper_download(*, db: Session) -> GetPaperDownload:
    return GetPaperDownload(
        build_paper_content(db=db),
        S3PaperDownloadSigner(),
        expires_in_seconds=DEFAULT_SIGNED_URL_TTL_SECONDS,
    )


def build_paper_ingestion(*, db: Session) -> IngestPaper:
    return IngestPaper(
        validator=DefaultPdfInputValidator(),
        limits=DefaultPaperIngestionLimits(),
        gateway=SqlPaperIngestionGateway(db),
    )


def build_pdf_url_source() -> SafePdfUrlSource:
    return SafePdfUrlSource()


def build_research_search(
    *,
    db: Session,
    cursor_secret: str,
) -> SearchResearch:
    return SearchResearch(
        SqlResearchSearch(db),
        build_research_search_cursor(cursor_secret),
    )


def build_complete_onboarding(*, db: Session) -> CompleteOnboarding:
    return CompleteOnboarding(
        writer=SqlAlchemyOnboardingWriter(db),
        display_names=CloudAuthDisplayNameWriter(),
        notifier=EmailOnboardingNotifier(),
        events=PostHogOnboardingEventRecorder(db),
    )


def build_stripe_webhook_processor(*, db: Session) -> ProcessStripeWebhook:
    return ProcessStripeWebhook(StripeWebhookAdapter(db))
