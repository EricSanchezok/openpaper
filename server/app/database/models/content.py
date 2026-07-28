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
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base, JsonValue
from .enums import (
    ConversationScopeType,
    DocumentProcessingStatus,
    PaperStatus,
)

if TYPE_CHECKING:
    from .identity import AuthUser
    from .jobs import DurableJob
    from .projects import Project, ProjectPaper
    from .research import ResearchItem


class UploadReservation(Base):
    __tablename__ = "upload_reservations"
    __table_args__ = (
        CheckConstraint(
            "reserved_size_kb >= 0",
            name="ck_upload_reservations_reserved_size_nonnegative",
        ),
        CheckConstraint(
            "reserved_reference_count IN (0, 1)",
            name="ck_upload_reservations_reserved_reference_count",
        ),
        Index("ix_upload_reservations_quota_owner", "quota_owner_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    quota_owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reserved_size_kb: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    reserved_reference_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    content_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    reference_created: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    job: Mapped["DurableJob"] = relationship(
        "DurableJob",
        foreign_keys=[id],
    )
    quota_owner: Mapped["AuthUser"] = relationship(
        "AuthUser",
        foreign_keys=[quota_owner_id],
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
    __table_args__ = (
        UniqueConstraint(
            "conversation_id",
            "sequence",
            name="uq_messages_conversation_sequence",
        ),
    )

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
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )
    research_items: Mapped[list["ResearchItem"]] = relationship(
        "ResearchItem",
        back_populates="source_message",
        order_by="ResearchItem.created_at",
        passive_deletes=True,
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

    scope_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ConversationScopeType.PAPER,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    scope_label_snapshot: Mapped[str | None] = mapped_column(String(240), nullable=True)
    context_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pinned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    paper: Mapped["Document | None"] = relationship(
        "Document",
        foreign_keys=[document_id],
        back_populates="conversations",
    )
    project: Mapped["Project | None"] = relationship(
        "Project",
        foreign_keys=[project_id],
        back_populates="conversations",
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
            "(scope_type = 'global' AND project_id IS NULL "
            "AND document_id IS NULL AND context_deleted_at IS NULL) OR "
            "(scope_type = 'project' AND document_id IS NULL AND "
            "((project_id IS NOT NULL AND context_deleted_at IS NULL) OR "
            "(project_id IS NULL AND context_deleted_at IS NOT NULL))) OR "
            "(scope_type = 'paper' AND project_id IS NULL AND "
            "((document_id IS NOT NULL AND context_deleted_at IS NULL) OR "
            "(document_id IS NULL AND context_deleted_at IS NOT NULL)))",
            name="ck_conversations_scope_consistency",
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
    library_papers: Mapped[list["LibraryPaper"]] = relationship(
        "LibraryPaper",
        secondary=lambda: LibraryPaperTag.__table__,
        back_populates="tags",
    )


class LibraryPaperTag(Base):
    __tablename__ = "library_paper_tags"

    library_paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("library_papers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paper_tags.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Document(Base):
    """One stored and parsed PDF, independent of any user's library."""

    __tablename__ = "documents"

    __table_args__ = (
        UniqueConstraint("sha256", name="uq_documents_sha256"),
        Index("ix_documents_ts_vector", "ts_vector", postgresql_using="gin"),
        CheckConstraint(
            "parser_backend IS NULL OR parser_backend IN ('mineru', 'pymupdf')",
            name="ck_documents_parser_backend",
        ),
        CheckConstraint(
            "parser_quality IS NULL OR parser_quality IN ('full', 'text_only')",
            name="ck_documents_parser_quality",
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_documents_processing_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(
        String(128), nullable=False, default="application/pdf"
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    s3_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    preview_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    institutions: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    keywords: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
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
    processing_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=DocumentProcessingStatus.PENDING,
        server_default=DocumentProcessingStatus.PENDING.value,
    )
    processing_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    gc_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    ts_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    page_offset_map: Mapped[dict[int, list[int]] | None] = mapped_column(
        JSONB, nullable=True
    )  # Maps page numbers to text offsets. Useful for re-annotation.
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
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

    library_entries: Mapped[list["LibraryPaper"]] = relationship(
        "LibraryPaper",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="paper",
        foreign_keys="Conversation.document_id",
        passive_deletes=True,
    )
    paper_images: Mapped[list["PaperImage"]] = relationship(
        "PaperImage", back_populates="paper", cascade="all, delete-orphan"
    )

    project_papers: Mapped[list["ProjectPaper"]] = relationship(
        "ProjectPaper", back_populates="document"
    )
    creator: Mapped["AuthUser | None"] = relationship(
        "AuthUser", back_populates="created_documents"
    )


class LibraryPaper(Base):
    """A user's personal library membership for a shared Document."""

    __tablename__ = "library_papers"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "document_id",
            name="uq_library_papers_user_document",
        ),
        Index("ix_library_papers_user_activity", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=PaperStatus.reading,
        server_default=PaperStatus.reading.value,
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    share_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    metadata_overrides: Mapped[dict[str, JsonValue]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="library_papers")
    document: Mapped["Document"] = relationship(
        "Document", back_populates="library_entries"
    )
    tags: Mapped[list["PaperTag"]] = relationship(
        "PaperTag",
        secondary=lambda: LibraryPaperTag.__table__,
        back_populates="library_papers",
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
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ts_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    paper: Mapped["Document"] = relationship("Document")


class PaperImage(Base):
    __tablename__ = "paper_images"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    s3_object_key: Mapped[str] = mapped_column(String, nullable=False)
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

    paper: Mapped["Document"] = relationship("Document", back_populates="paper_images")
