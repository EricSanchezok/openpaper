"""Typed SQLAlchemy model registry for the Scholens product schema."""

from .base import Base, JsonScalar, JsonValue
from .enums import (
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
from .identity import AuthUser, UserProfile
from .jobs import DurableJob, JobDispatch, JobsWebhookNonce
from .integrations import ZoteroConnection, ZoteroImportedItem, ZoteroOAuthPending
from .conversations import Conversation, Message
from .documents import (
    LibraryPaper,
    LibraryPaperTag,
    Document,
    DocumentPassage,
    PaperTag,
    UploadReservation,
)
from .usage import TokenUsageEvent, TokenWeeklyUsage
from .projects import Project, ProjectCollaborator, ProjectInvitation, ProjectPaper
from .research import (
    AnnotationComment,
    CitationOutput,
    HighlightThread,
    ResearchAudioOverview,
    ResearchDataTable,
    ResearchItem,
)
from .commerce import (
    Onboarding,
    StripeWebhookEvent,
    Subscription,
)

__all__ = [
    "AuthUser",
    "Base",
    "ConversationScopeType",
    "DocumentProcessingStatus",
    "Conversation",
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
    "UserProfile",
    "ZoteroConnection",
    "ZoteroImportSource",
    "ZoteroImportStatus",
    "ZoteroImportedItem",
    "ZoteroOAuthPending",
]
