from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base, JsonValue
from .enums import ConversableType, JobStatus, PaperStatus

if TYPE_CHECKING:
    from .identity import AuthUser
    from .projects import ProjectPaper


class PaperUploadJob(Base):
    __tablename__ = "paper_upload_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=JobStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # For tracking task in Celery

    user: Mapped["AuthUser"] = relationship(
        "AuthUser", back_populates="paper_upload_jobs"
    )


class TokenUsageEvent(Base):
    """Immutable provider usage returned by one DeepSeek API call."""

    __tablename__ = "token_usage_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_token_usage_idempotency_key"),
        Index("ix_token_usage_user_week", "user_id", "week_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="deepseek"
    )
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    reasoning_level: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_hit_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_miss_tokens: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="settled")


class TokenWeeklyUsage(Base):
    """Fast current-week aggregate; the immutable event table is authoritative."""

    __tablename__ = "token_weekly_usage"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    used_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class JobsWebhookNonce(Base):
    """Consumed Jobs request nonce; the primary key prevents cross-instance replay."""

    __tablename__ = "jobs_webhook_nonces"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)  # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # References from the paper. Key 'citations' maps to list of ResponseCitation dicts
    references: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB, nullable=True
    )

    # Agent trajectory (tool calls / thinking / subagent steps) for this turn,
    # so the user can inspect what the model did. See schemas for shape.
    trace: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    # @-mention context the user attached to this (user) turn: a denormalized
    # snapshot list of [{kind, id, title}] so it renders faithfully even if the
    # mentioned paper/project is later renamed or deleted.
    scope: Mapped[list[dict[str, JsonValue]] | None] = mapped_column(
        JSONB, nullable=True
    )
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # To maintain message order
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("auth.users.id"), nullable=True
    )

    user: Mapped["AuthUser | None"] = relationship(
        "AuthUser", back_populates="messages"
    )
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="Artifact.created_at",
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(
        String(240), nullable=False, default="New conversation"
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Polymorphic Columns
    conversable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    conversable_type: Mapped[str] = mapped_column(
        String, nullable=False, default=ConversableType.PAPER
    )
    scope_label_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Specific relationship for papers
    paper: Mapped["Paper | None"] = relationship(
        "Paper",
        primaryjoin=lambda: and_(
            foreign(Conversation.conversable_id) == Paper.id,
            Conversation.conversable_type == ConversableType.PAPER.value,
        ),
        viewonly=True,
    )

    user: Mapped["AuthUser | None"] = relationship(
        "AuthUser", back_populates="conversations"
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        order_by=Message.sequence,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "(conversable_type = 'paper' AND conversable_id IS NOT NULL) OR "
            "(conversable_type = 'project' AND conversable_id IS NOT NULL) OR "
            "(conversable_type = 'everything' AND conversable_id IS NULL)",
            name="check_conversable_consistency",
        ),
        Index(
            "ix_conversations_user_archive_activity",
            "user_id",
            "archived_at",
            "updated_at",
        ),
        Index(
            "ix_conversations_user_pinned",
            "user_id",
            "pinned_at",
        ),
    )


class Artifact(Base):
    """A first-party artifact (citation card today; charts/images later).

    Scope mirrors `ConversableType` so the same primitive that targets a
    conversation also targets an artifact's surfacing — a project panel filters
    `scope_type='project' AND scope_id=<project_id>`, a paper view filters
    `scope_type='paper' AND scope_id=<paper_id>`, and `everything` artifacts
    leave `scope_id NULL`.
    """

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    kind: Mapped[str] = mapped_column(String, nullable=False)  # ArtifactKind value
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, nullable=False)

    # Provenance: which assistant message produced this artifact.
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Scope — denormalized from the originating conversation so panel queries
    # are a single indexed lookup, no joins through messages → conversations.
    scope_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # ConversableType value
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    message: Mapped["Message"] = relationship("Message", back_populates="artifacts")

    __table_args__ = (
        Index(
            "ix_artifacts_scope",
            "scope_type",
            "scope_id",
            "kind",
            "created_at",
        ),
        Index("ix_artifacts_message_id", "message_id"),
    )


class PaperTag(Base):
    __tablename__ = "paper_tags"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Optional color for the tag
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="paper_tags")
    papers: Mapped[list["Paper"]] = relationship(
        "Paper",
        secondary=lambda: PaperTagAssociation.__table__,
        back_populates="tags",
    )


class PaperTagAssociation(Base):
    __tablename__ = "paper_tag_association"

    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paper_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Paper(Base):
    __tablename__ = "papers"

    # Define the GIN index for full-text search
    __table_args__ = (
        Index("ix_papers_ts_vector", "ts_vector", postgresql_using="gin"),
        CheckConstraint(
            "parser_backend IS NULL OR parser_backend IN ('mineru', 'pymupdf')",
            name="ck_papers_parser_backend",
        ),
        CheckConstraint(
            "parser_quality IS NULL OR parser_quality IN ('full', 'text_only')",
            name="ck_papers_parser_quality",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # we can change the default to TODO once we have some kind of bulk paper upload? for now, every upload automatically converts to reading
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=PaperStatus.reading
    )
    file_url: Mapped[str] = mapped_column(String, nullable=False)
    preview_url: Mapped[str | None] = mapped_column(String, nullable=True)
    s3_object_key: Mapped[str | None] = mapped_column(String, nullable=True)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    institutions: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_citations: Mapped[list[dict[str, JsonValue]] | None] = mapped_column(
        JSONB, nullable=True
    )
    publish_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    starter_questions: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    parser_markdown_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_archive_s3_key: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_backend: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_quality: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_version: Mapped[str | None] = mapped_column(String, nullable=True)
    parser_warning_code: Mapped[str | None] = mapped_column(String, nullable=True)
    ts_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    page_offset_map: Mapped[dict[int, list[int]] | None] = mapped_column(
        JSONB, nullable=True
    )  # Maps page numbers to text offsets. Useful for re-annotation.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("auth.users.id"), nullable=True
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    upload_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paper_upload_jobs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cached presigned URL fields
    cached_presigned_url: Mapped[str | None] = mapped_column(String, nullable=True)
    presigned_url_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Optional fields for sharing
    is_public: Mapped[bool | None] = mapped_column(Boolean, default=False)
    share_id: Mapped[str | None] = mapped_column(
        String, unique=True, nullable=True, index=True
    )

    # Additional metadata
    doi: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Digital Object Identifier
    journal: Mapped[str | None] = mapped_column(String, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    attempted_metadata_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Per-field provenance for agent-filled metadata:
    # {field: {source_url, filled_by, confidence, filled_at}}
    field_provenance: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB, nullable=True
    )

    size_in_kb: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Size of the paper file in KB

    # Some papers can be forked/duplicated from other papers (across users). To handle this, we store the parent paper ID of the original paper.
    parent_paper_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped["AuthUser | None"] = relationship("AuthUser", back_populates="papers")
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="paper",
        cascade="all, delete-orphan",
        primaryjoin=lambda: and_(
            Paper.id == foreign(Conversation.conversable_id),
            Conversation.conversable_type == ConversableType.PAPER.value,
        ),
    )
    paper_notes: Mapped[list["PaperNote"]] = relationship(
        "PaperNote", back_populates="paper", cascade="all, delete-orphan"
    )

    audio_overviews: Mapped[list["AudioOverview"]] = relationship(
        "AudioOverview",
        cascade="all, delete-orphan",
        primaryjoin=lambda: and_(
            Paper.id == foreign(AudioOverview.conversable_id),
            AudioOverview.conversable_type == ConversableType.PAPER.value,
        ),
        overlaps="audio_overviews",
    )

    audio_overview_jobs: Mapped[list["AudioOverviewJob"]] = relationship(
        "AudioOverviewJob",
        cascade="all, delete-orphan",
        primaryjoin=lambda: and_(
            Paper.id == foreign(AudioOverviewJob.conversable_id),
            AudioOverviewJob.conversable_type == ConversableType.PAPER.value,
        ),
        overlaps="audio_overview_jobs",
    )

    paper_images: Mapped[list["PaperImage"]] = relationship(
        "PaperImage", back_populates="paper", cascade="all, delete-orphan"
    )

    project_papers: Mapped[list["ProjectPaper"]] = relationship(
        "ProjectPaper", back_populates="paper"
    )

    tags: Mapped[list["PaperTag"]] = relationship(
        "PaperTag",
        secondary=lambda: PaperTagAssociation.__table__,
        back_populates="papers",
    )


class PaperPassage(Base):
    __tablename__ = "paper_passages"

    __table_args__ = (
        UniqueConstraint("paper_id", "start_line"),
        Index("ix_paper_passages_ts_vector", "ts_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ts_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    paper: Mapped["Paper"] = relationship("Paper")


class PaperImage(Base):
    __tablename__ = "paper_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    s3_object_key: Mapped[str] = mapped_column(String, nullable=False)
    image_url: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, nullable=False)  # e.g., 'png', 'jpg'

    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Size of the image in bytes
    width: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Width of the image in pixels
    height: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Height of the image in pixels

    page_number: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Page number where the image is located
    image_index: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Index of the image in the paper

    caption: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Optional caption for the image

    placeholder_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # Placeholder ID for the image

    paper: Mapped["Paper"] = relationship("Paper", back_populates="paper_images")


class PaperNote(Base):
    __tablename__ = "paper_notes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Ensure each document has only one associated paper note
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("auth.users.id"), nullable=True
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="paper_notes")

    paper: Mapped["Paper"] = relationship("Paper", back_populates="paper_notes")


class Highlight(Base):
    __tablename__ = "highlights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # HighlightType enum value)

    # Position (exact for user, hints for AI)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    position: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)

    # Role
    # This can be user for user-created highlights or assistant for AI-generated highlights
    role: Mapped[str] = mapped_column(
        String, nullable=False, default="user"
    )  # 'user' or 'assistant'
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("auth.users.id"), nullable=True
    )
    color: Mapped[str | None] = mapped_column(String, nullable=True, default="blue")
    zotero_annotation_key: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index(
            "uq_highlight_paper_zotero_annotation_key",
            "paper_id",
            "zotero_annotation_key",
            unique=True,
            postgresql_where=(zotero_annotation_key.isnot(None)),
        ),
    )

    # Relationships
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="highlights")
    annotations: Mapped[list["Annotation"]] = relationship(
        "Annotation", back_populates="highlight", cascade="all, delete-orphan"
    )


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # The associated highlight
    highlight_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("highlights.id"), nullable=False
    )

    # The associated paper
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Role tracking
    role: Mapped[str] = mapped_column(
        String, nullable=False, default="user"
    )  # 'user' or 'assistant'
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id"), nullable=False
    )

    # Relationships
    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="annotations")
    highlight: Mapped["Highlight"] = relationship(
        "Highlight", back_populates="annotations"
    )


class AudioOverviewJob(Base):
    __tablename__ = "audio_overview_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )

    conversable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    conversable_type: Mapped[str] = mapped_column(
        String, nullable=False, default=ConversableType.PAPER
    )

    status: Mapped[str] = mapped_column(
        String, nullable=False, default=JobStatus.PENDING
    )
    status_message: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["AuthUser"] = relationship(
        "AuthUser", back_populates="audio_overview_jobs"
    )

    # Specific relationship for papers (viewonly)
    paper: Mapped["Paper | None"] = relationship(
        "Paper",
        primaryjoin=lambda: and_(
            foreign(AudioOverviewJob.conversable_id) == Paper.id,
            AudioOverviewJob.conversable_type == ConversableType.PAPER.value,
        ),
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            "(conversable_type = 'paper' AND conversable_id IS NOT NULL) OR "
            "(conversable_type = 'project' AND conversable_id IS NOT NULL) OR "
            "(conversable_type = 'everything' AND conversable_id IS NULL)",
            name="check_audio_overview_job_conversable_consistency",
        ),
    )


class AudioOverview(Base):
    __tablename__ = "audio_overviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )

    s3_object_key: Mapped[str] = mapped_column(
        String, nullable=False
    )  # Store the S3 object key of the wav file

    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)

    citations: Mapped[list[dict[str, JsonValue]] | None] = mapped_column(
        JSONB, nullable=True
    )  # Store citations in a JSONB format for flexibility. Typically, it would be a list of dicts with keys like `index` and `text`.

    title: Mapped[str | None] = mapped_column(String, nullable=True)

    conversable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    conversable_type: Mapped[str] = mapped_column(
        String, nullable=False, default=ConversableType.PAPER
    )

    # Specific relationship for papers (viewonly)
    paper: Mapped["Paper | None"] = relationship(
        "Paper",
        primaryjoin=lambda: and_(
            foreign(AudioOverview.conversable_id) == Paper.id,
            AudioOverview.conversable_type == ConversableType.PAPER.value,
        ),
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint(
            "(conversable_type = 'paper' AND conversable_id IS NOT NULL) OR "
            "(conversable_type = 'project' AND conversable_id IS NOT NULL) OR "
            "(conversable_type = 'everything' AND conversable_id IS NULL)",
            name="check_audio_overview_conversable_consistency",
        ),
    )
