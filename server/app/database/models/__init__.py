"""Typed SQLAlchemy model registry for the Scholens product schema."""

from app.shared.domain import JsonScalar, JsonValue
from app.shared.infrastructure.persistence import Base
from app.shared.domain.enums import (
    ConversationScopeType,
    DocumentProcessingStatus,
    HighlightType,
    JobDispatchStatus,
    JobOperation,
    JobStatus,
    PaperStatus,
    ReasoningLevel,
    ResearchItemKind,
    ResearchScopeType,
    RoleType,
    SubscriptionPlan,
    SubscriptionStatus,
    StripeWebhookEventStatus,
    ZoteroImportSource,
    ZoteroImportStatus,
)
from app.modules.identity.infrastructure.models import AuthUser, UserProfile
from app.modules.access_keys.infrastructure.models import AccessKey
from app.modules.integrations.connectors.infrastructure.models import (
    ConnectorConnection,
)
from app.modules.operation_journal.infrastructure.models import (
    OperationJournalEntryModel,
)
from app.modules.identity.infrastructure.onboarding_model import Onboarding
from app.modules.jobs.infrastructure.models import (
    DurableJob,
    JobDispatch,
    JobsWebhookNonce,
)
from app.modules.integrations.zotero.infrastructure.models import (
    ZoteroConnection,
    ZoteroImportedItem,
    ZoteroOAuthPending,
)
from app.modules.conversations.infrastructure.models import (
    Conversation,
    ConversationContextDocument,
    ConversationContextProject,
    Message,
)
from app.modules.papers.infrastructure.models import (
    LibraryPaper,
    LibraryPaperTag,
    Document,
    DocumentPassage,
    PaperTag,
    UploadReservation,
)
from app.modules.billing.infrastructure.usage_models import (
    TokenUsageEvent,
    TokenWeeklyUsage,
)
from app.modules.projects.infrastructure.models import (
    Project,
    ProjectCollaborator,
    ProjectInvitation,
    ProjectPaper,
)
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    CitationOutput,
    HighlightThread,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
)
from app.modules.billing.infrastructure.models import StripeWebhookEvent, Subscription
from app.database.models.tool_invocation import ToolInvocation
from app.modules.translations.infrastructure.models import TranslationPreference

__all__ = [
    "AuthUser",
    "AccessKey",
    "Base",
    "ConversationScopeType",
    "ConnectorConnection",
    "DocumentProcessingStatus",
    "Conversation",
    "ConversationContextDocument",
    "ConversationContextProject",
    "HighlightType",
    "DurableJob",
    "JobDispatch",
    "JobDispatchStatus",
    "JobOperation",
    "JobStatus",
    "JobsWebhookNonce",
    "LibraryPaper",
    "LibraryPaperTag",
    "JsonScalar",
    "JsonValue",
    "Message",
    "Onboarding",
    "OperationJournalEntryModel",
    "Document",
    "DocumentPassage",
    "PaperStatus",
    "PaperTag",
    "UploadReservation",
    "Project",
    "ProjectCollaborator",
    "ProjectInvitation",
    "ProjectPaper",
    "ReasoningLevel",
    "ResearchAudioOverview",
    "ResearchDataTable",
    "ResearchItem",
    "ResearchItemKind",
    "ResearchScopeType",
    "CitationOutput",
    "HighlightThread",
    "AnnotationComment",
    "RoleType",
    "Subscription",
    "SubscriptionPlan",
    "SubscriptionStatus",
    "StripeWebhookEvent",
    "StripeWebhookEventStatus",
    "TokenUsageEvent",
    "TokenWeeklyUsage",
    "ToolInvocation",
    "TranslationPreference",
    "UserProfile",
    "ZoteroConnection",
    "ZoteroImportSource",
    "ZoteroImportStatus",
    "ZoteroImportedItem",
    "ZoteroOAuthPending",
]
