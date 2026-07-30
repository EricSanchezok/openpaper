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


class JobOperation(str, Enum):
    PDF_PROCESS = "pdf_process"
    PDF_POSTPROCESS = "pdf_postprocess"
    AUDIO_GENERATE = "audio_generate"
    DATA_TABLE_GENERATE = "data_table_generate"
    ZOTERO_IMPORT = "zotero_import"
    ZOTERO_POSTPROCESS = "zotero_postprocess"
    DOCUMENT_GC = "document_gc"
    STORAGE_DELETE = "storage_delete"


class JobDispatchStatus(str, Enum):
    PENDING = "pending"
    PUBLISHING = "publishing"
    PUBLISHED = "published"


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
