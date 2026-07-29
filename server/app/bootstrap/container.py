"""The application's single composition root.

Transport adapters import builders from this module and never choose concrete
infrastructure themselves. Keeping every adapter decision here makes storage,
search, identity, billing, and integrations replaceable without changing an
HTTP, Agent, or MCP contract.
"""

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
from app.bootstrap.adapters.paper_ingestion import (
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
from app.modules.billing.application.billing import Billing
from app.modules.billing.infrastructure.application_gateway import (
    EmailBillingNotifier,
    PostHogBillingEvents,
    SqlAlchemySubscriptionStore,
    SqlAlchemyUsageReader,
    StripePaymentProvider,
)
from app.modules.billing.infrastructure.config import (
    MONTHLY_PRICE_ID,
    YEARLY_PRICE_ID,
)
from app.modules.billing.infrastructure.webhook_adapter import StripeWebhookAdapter
from app.modules.papers.application.tags import LibraryTags
from app.modules.papers.infrastructure.tag_gateway import (
    SqlAlchemyLibraryTagGateway,
)
from app.modules.papers.application.discovery import DiscoverPapers
from app.modules.papers.infrastructure.discovery import (
    AiExternalDiscoveryRateLimiter,
    OpenAlexPaperCatalog,
    PostHogDiscoveryEventRecorder,
    SqlDiscoveryDocumentGateway,
)
from app.modules.papers.application.details import GetPaperDetails
from app.modules.papers.application.citations import ResolveCitation
from app.modules.papers.application.library import PaperLibrary
from app.modules.papers.infrastructure.details import SqlAlchemyPaperDetails
from app.modules.papers.infrastructure.library_gateway import (
    SqlAlchemyPaperLibraryGateway,
)
from app.modules.projects.application.projects import Projects
from app.bootstrap.adapters.project_gateway import (
    EmailProjectInvitationNotifier,
    PostHogProjectEvents,
    SqlAlchemyProjectGateway,
)
from app.modules.research.application.items import ResearchItems
from app.modules.research.infrastructure.item_gateway import (
    SqlAlchemyResearchItemGateway,
)
from app.modules.jobs.application.jobs import Jobs
from app.modules.jobs.application.callbacks import JobCallbacks
from app.modules.jobs.application.authentication import ProtectJobCallback
from app.modules.jobs.infrastructure.application_gateway import (
    SqlAlchemyJobsGateway,
)
from app.modules.research.application.generation import (
    GenerationDocuments,
    ResearchGeneration,
)
from app.modules.research.infrastructure.generation import (
    DefaultGenerationCapacity,
)
from app.modules.conversations.application.conversations import Conversations
from app.modules.conversations.application.chat import ConversationChat
from app.bootstrap.adapters.conversation_lifecycle import (
    LlmConversationTitleGenerator,
    PostHogConversationEvents,
    SqlAlchemyConversationGateway,
)
from app.shared.application import SignedCursorCodec
from app.modules.identity.application.identity import Identity
from app.modules.identity.infrastructure.application_gateway import (
    SqlAlchemyIdentityGateway,
)
from app.modules.identity.infrastructure import cloud_auth as cloud_auth_adapter
from app.modules.papers.application.topics import PaperTopics
from app.modules.papers.infrastructure.topics import SqlAlchemyPaperTopics
from app.modules.integrations.zotero.application.zotero import Zotero
from app.modules.integrations.zotero.infrastructure.application_gateway import (
    DefaultZoteroGateway,
    PostHogZoteroEvents,
)
from app.bootstrap.adapters.billing_capacity import (
    BillingLibraryCapacity,
    BillingProjectCapacity,
    BillingZoteroImportCapacity,
)
from sqlalchemy.orm import Session

optional_cloud_user_dependency = cloud_auth_adapter.get_optional_cloud_user


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


def build_billing(*, db: Session) -> Billing:
    return Billing(
        subscriptions=SqlAlchemySubscriptionStore(db),
        payments=StripePaymentProvider(),
        usage=SqlAlchemyUsageReader(db),
        events=PostHogBillingEvents(db),
        notifier=EmailBillingNotifier(),
        monthly_price_id=MONTHLY_PRICE_ID,
        yearly_price_id=YEARLY_PRICE_ID,
    )


def build_library_tags(*, db: Session) -> LibraryTags:
    return LibraryTags(SqlAlchemyLibraryTagGateway(db))


def build_paper_discovery(*, db: Session, cursor_secret: str) -> DiscoverPapers:
    return DiscoverPapers(
        catalog=OpenAlexPaperCatalog(),
        documents=SqlDiscoveryDocumentGateway(db),
        rate_limiter=AiExternalDiscoveryRateLimiter(),
        events=PostHogDiscoveryEventRecorder(db),
        cursors=SignedCursorCodec(
            cursor_secret,
            revision="external-discovery-v1",
            error_code="discovery_cursor_expired",
        ),
    )


def build_paper_library(*, db: Session) -> PaperLibrary:
    return PaperLibrary(
        gateway=SqlAlchemyPaperLibraryGateway(db),
        capacity=BillingLibraryCapacity(db),
        signer=S3PaperDownloadSigner(),
    )


def build_paper_details(*, db: Session) -> GetPaperDetails:
    return GetPaperDetails(
        SqlAlchemyPaperDetails(db),
        build_project_document_visibility(db=db),
    )


def build_citation_resolver(*, db: Session) -> ResolveCitation:
    # Lazy because the optional agentic metadata recovery path imports Agent
    # tool definitions, which themselves delegate through this container.
    from app.bootstrap.adapters.citation_metadata import (
        DefaultCitationMetadataGateway,
    )

    return ResolveCitation(DefaultCitationMetadataGateway(db))


def build_projects(*, db: Session) -> Projects:
    return Projects(
        gateway=SqlAlchemyProjectGateway(db),
        capacity=BillingProjectCapacity(db),
        events=PostHogProjectEvents(db),
        invitations=EmailProjectInvitationNotifier(),
        signer=S3PaperDownloadSigner(),
    )


def build_research_items(*, db: Session) -> ResearchItems:
    return ResearchItems(SqlAlchemyResearchItemGateway(db))


def build_jobs(*, db: Session) -> Jobs:
    return Jobs(SqlAlchemyJobsGateway(db))


def build_job_callback_protection() -> ProtectJobCallback:
    from app.modules.jobs.infrastructure.authentication import (
        SqlAlchemyCallbackNonceStore,
    )

    return ProtectJobCallback(SqlAlchemyCallbackNonceStore())


def build_job_callbacks(*, db: Session) -> JobCallbacks:
    # Callback adapters touch several domain modules and are loaded only by
    # the internal callback transport, avoiding composition-root import cycles.
    from app.modules.jobs.application.callbacks import RegisteredJobCallback
    from app.modules.jobs.application.contracts import (
        AudioOverviewWebhookData,
        DataTableWebhookData,
        JobCallbackIdentity,
        PdfProcessingWebhookData,
        StorageDeleteCallback,
    )
    from app.bootstrap.adapters.job_callback_handlers import (
        AudioCompletion,
        DataTableCompletion,
        DocumentGcCompletion,
        PdfPostprocessCompletion,
        PdfProcessCompletion,
        SqlAlchemyJobLifecycle,
        StorageDeleteCompletion,
        ZoteroPostprocessCompletion,
        ZoteroSyncSchedule,
    )
    from app.shared.domain.enums import JobOperation

    return JobCallbacks(
        lifecycle=SqlAlchemyJobLifecycle(db),
        handlers={
            JobOperation.PDF_PROCESS: RegisteredJobCallback(
                PdfProcessingWebhookData, PdfProcessCompletion(db)
            ),
            JobOperation.PDF_POSTPROCESS: RegisteredJobCallback(
                JobCallbackIdentity, PdfPostprocessCompletion(db)
            ),
            JobOperation.DOCUMENT_GC: RegisteredJobCallback(
                JobCallbackIdentity, DocumentGcCompletion(db)
            ),
            JobOperation.STORAGE_DELETE: RegisteredJobCallback(
                StorageDeleteCallback, StorageDeleteCompletion(db)
            ),
            JobOperation.ZOTERO_POSTPROCESS: RegisteredJobCallback(
                JobCallbackIdentity, ZoteroPostprocessCompletion(db)
            ),
            JobOperation.AUDIO_GENERATE: RegisteredJobCallback(
                AudioOverviewWebhookData, AudioCompletion(db)
            ),
            JobOperation.DATA_TABLE_GENERATE: RegisteredJobCallback(
                DataTableWebhookData, DataTableCompletion(db)
            ),
        },
        schedules=ZoteroSyncSchedule(db),
    )


def build_research_generation(*, db: Session) -> ResearchGeneration:
    project_documents = build_project_document_visibility(db=db)
    return ResearchGeneration(
        documents=GenerationDocuments(
            content=build_paper_content(db=db),
            project_documents=project_documents,
        ),
        jobs=SqlAlchemyJobsGateway(db),
        capacity=DefaultGenerationCapacity(db),
    )


def build_conversations(*, db: Session, cursor_secret: str) -> Conversations:
    return Conversations(
        gateway=SqlAlchemyConversationGateway(db),
        titles=LlmConversationTitleGenerator(db),
        events=PostHogConversationEvents(db),
        message_cursors=SignedCursorCodec(
            cursor_secret,
            revision="conversation-messages-v1",
            error_code="conversation_message_cursor_expired",
        ),
    )


def build_conversation_chat(*, db: Session) -> ConversationChat:
    # Lazy import avoids the LLM tool graph importing this composition root
    # while the root itself is still being initialized.
    from app.bootstrap.adapters.conversation_chat import (
        DefaultConversationChatGateway,
    )

    return ConversationChat(DefaultConversationChatGateway(db))


def build_identity(*, db: Session) -> Identity:
    return Identity(SqlAlchemyIdentityGateway(db))


def build_paper_topics(*, db: Session) -> PaperTopics:
    return PaperTopics(SqlAlchemyPaperTopics(db))


def build_zotero(*, db: Session) -> Zotero:
    return Zotero(
        gateway=DefaultZoteroGateway(db),
        capacity=BillingZoteroImportCapacity(db),
        events=PostHogZoteroEvents(db),
        idempotency=SqlAlchemyJobsGateway(db),
    )
