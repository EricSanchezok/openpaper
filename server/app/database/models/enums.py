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


class ProjectRoles(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class ReferralStatus(str, Enum):
    ATTRIBUTED = "attributed"
    CREDIT_PENDING = "credit_pending"
    CREDIT_AVAILABLE = "credit_available"
    REJECTED_FRAUD = "rejected_fraud"
    CLAWED_BACK = "clawed_back"


class ReferralAttributionMethod(str, Enum):
    LINK = "link"
    MANUAL_CODE = "manual_code"


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


class ArtifactKind(str, Enum):
    """First-party artifacts produced by chat (or other agentic flows).

    The DB stores the value as a plain string; this enum is the canonical set
    used at write time and for CRUD typing.
    """

    CITATION = "citation"


class HighlightType(str, Enum):
    TOPIC = "topic"
    MOTIVATION = "motivation"
    METHOD = "method"
    EVIDENCE = "evidence"
    RESULT = "result"
    IMPACT = "impact"
    GENERAL = "general"
