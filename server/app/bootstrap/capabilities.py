"""Session-bound application capabilities exposed to every transport."""

from __future__ import annotations

from functools import cached_property

from app.bootstrap.container import (
    build_billing,
    build_citation_resolver,
    build_complete_onboarding,
    build_conversation_chat,
    build_conversations,
    build_identity,
    build_job_callbacks,
    build_jobs,
    build_library_tags,
    build_paper_content,
    build_paper_details,
    build_paper_discovery,
    build_paper_download,
    build_paper_ingestion,
    build_paper_library,
    build_paper_search,
    build_paper_topics,
    build_pdf_url_source,
    build_project_document_visibility,
    build_projects,
    build_research_generation,
    build_research_items,
    build_research_search,
    build_stripe_webhook_processor,
    build_zotero,
)
from app.bootstrap.settings import AppSettings
from app.modules.billing.application.billing import Billing
from app.modules.billing.application.webhooks import ProcessStripeWebhook
from app.modules.conversations.application.chat import ConversationChat
from app.modules.conversations.application.conversations import Conversations
from app.modules.identity.application.identity import Identity
from app.modules.identity.application.onboarding import CompleteOnboarding
from app.modules.integrations.zotero.application.zotero import Zotero
from app.modules.jobs.application.callbacks import JobCallbacks
from app.modules.jobs.application.jobs import Jobs
from app.modules.papers.application.citations import ResolveCitation
from app.modules.papers.application.content import PaperContentCapabilities
from app.modules.papers.application.details import GetPaperDetails
from app.modules.papers.application.discovery import DiscoverPapers
from app.modules.papers.application.downloads import GetPaperDownload
from app.modules.papers.application.ingestion import IngestPaper, PdfUrlSource
from app.modules.papers.application.library import PaperLibrary
from app.modules.papers.application.search import (
    GetPaperSearchStats,
    SearchCursorCodec,
    SearchPapers,
)
from app.modules.papers.application.tags import LibraryTags
from app.modules.papers.application.topics import PaperTopics
from app.modules.projects.application.projects import Projects
from app.modules.research.application.generation import ResearchGeneration
from app.modules.research.application.items import ResearchItems
from app.modules.research.application.search import SearchResearch
from sqlalchemy.orm import Session


class ApplicationCapabilities:
    """The canonical application surface for one executor operation."""

    def __init__(self, session: Session, settings: AppSettings) -> None:
        self._session = session
        self._settings = settings

    @cached_property
    def identity(self) -> Identity:
        return build_identity(db=self._session)

    @cached_property
    def paper_search(self) -> SearchPapers:
        return SearchPapers(
            build_paper_search(
                backend=self._settings.paper_search_backend,
                db=self._session,
            ),
            SearchCursorCodec(self._settings.paper_search_cursor_secret),
            build_project_document_visibility(db=self._session),
        )

    @cached_property
    def paper_search_stats(self) -> GetPaperSearchStats:
        return GetPaperSearchStats(
            build_paper_search(
                backend=self._settings.paper_search_backend,
                db=self._session,
            ),
            build_project_document_visibility(db=self._session),
        )

    @cached_property
    def paper_content(self) -> PaperContentCapabilities:
        return build_paper_content(db=self._session)

    @cached_property
    def paper_download(self) -> GetPaperDownload:
        return build_paper_download(db=self._session)

    @cached_property
    def paper_ingestion(self) -> IngestPaper:
        return build_paper_ingestion(db=self._session)

    @cached_property
    def pdf_url_source(self) -> PdfUrlSource:
        return build_pdf_url_source()

    @cached_property
    def research_search(self) -> SearchResearch:
        return build_research_search(
            db=self._session,
            cursor_secret=self._settings.paper_search_cursor_secret,
        )

    @cached_property
    def onboarding(self) -> CompleteOnboarding:
        return build_complete_onboarding(db=self._session)

    @cached_property
    def stripe_webhooks(self) -> ProcessStripeWebhook:
        return build_stripe_webhook_processor(db=self._session)

    @cached_property
    def billing(self) -> Billing:
        return build_billing(db=self._session)

    @cached_property
    def library_tags(self) -> LibraryTags:
        return build_library_tags(db=self._session)

    @cached_property
    def paper_discovery(self) -> DiscoverPapers:
        return build_paper_discovery(
            db=self._session,
            cursor_secret=self._settings.paper_search_cursor_secret,
        )

    @cached_property
    def paper_library(self) -> PaperLibrary:
        return build_paper_library(db=self._session)

    @cached_property
    def paper_details(self) -> GetPaperDetails:
        return build_paper_details(db=self._session)

    @cached_property
    def citations(self) -> ResolveCitation:
        return build_citation_resolver(db=self._session)

    @cached_property
    def projects(self) -> Projects:
        return build_projects(db=self._session)

    @cached_property
    def research_items(self) -> ResearchItems:
        return build_research_items(db=self._session)

    @cached_property
    def jobs(self) -> Jobs:
        return build_jobs(db=self._session)

    @cached_property
    def job_callbacks(self) -> JobCallbacks:
        return build_job_callbacks(db=self._session)

    @cached_property
    def research_generation(self) -> ResearchGeneration:
        return build_research_generation(db=self._session)

    @cached_property
    def conversations(self) -> Conversations:
        return build_conversations(
            db=self._session,
            cursor_secret=self._settings.paper_search_cursor_secret,
        )

    @cached_property
    def conversation_chat(self) -> ConversationChat:
        return build_conversation_chat(db=self._session)

    @cached_property
    def paper_topics(self) -> PaperTopics:
        return build_paper_topics(db=self._session)

    @cached_property
    def zotero(self) -> Zotero:
        return build_zotero(db=self._session)
