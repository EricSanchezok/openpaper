from enum import Enum


class SubscriptionPlan(str, Enum):
    BASIC = "basic"
    RESEARCHER = "researcher"


# When a user has a RESEARCHER (or more advanced) subscription,
# they can have one of the following statuses.


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    PAST_DUE = "past_due"
    INCOMPLETE = "incomplete"
    TRIALING = "trialing"
    UNPAID = "unpaid"


class StripeWebhookEventStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    IGNORED = "ignored"


class ReasoningLevel(str, Enum):
    STANDARD = "standard"
    DEEP = "deep"


class ZoteroImportSource(str, Enum):
    PDF_ATTACHMENT = "pdf_attachment"
    URL = "url"


class ZoteroImportStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DocumentProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class RoleType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class PaperStatus(str, Enum):
    todo = "todo"
    reading = "reading"
    completed = "completed"


class ConversableType(str, Enum):
    PAPER = "paper"
    PROJECT = "project"
    EVERYTHING = (
        "everything"  # For conversations that are across the user's entire library
    )


class ConversationScopeType(str, Enum):
    GLOBAL = "global"
    PROJECT = "project"
    PAPER = "paper"


class ResearchItemKind(str, Enum):
    HIGHLIGHT_THREAD = "highlight_thread"
    CITATION = "citation"
    AUDIO_OVERVIEW = "audio_overview"
    DATA_TABLE = "data_table"


class ResearchScopeType(str, Enum):
    PERSONAL = "personal"
    DOCUMENT = "document"
    PROJECT = "project"


class HighlightType(str, Enum):
    TOPIC = "topic"
    MOTIVATION = "motivation"
    METHOD = "method"
    EVIDENCE = "evidence"
    RESULT = "result"
    IMPACT = "impact"
    GENERAL = "general"
