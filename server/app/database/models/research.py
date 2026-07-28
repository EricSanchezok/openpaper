"""Shared metadata and strongly typed research outputs."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, JsonValue
from .enums import ResearchItemKind, ResearchScopeType

if TYPE_CHECKING:
    from .conversations import Message
    from .documents import Document
    from .identity import AuthUser
    from .jobs import DurableJob
    from .projects import Project


class ResearchItem(Base):
    __tablename__ = "research_items"
    __table_args__ = (
        CheckConstraint(
            "(scope_type = 'personal' AND document_id IS NULL AND project_id IS NULL) "
            "OR (scope_type = 'document' AND document_id IS NOT NULL "
            "AND project_id IS NULL) "
            "OR (scope_type = 'project' AND project_id IS NOT NULL "
            "AND document_id IS NULL)",
            name="ck_research_items_scope_consistency",
        ),
        CheckConstraint(
            "scope_type != 'personal' OR NOT is_shared",
            name="ck_research_items_personal_private",
        ),
        CheckConstraint(
            "kind != 'highlight_thread' OR scope_type = 'document'",
            name="ck_research_items_highlight_document_scope",
        ),
        Index(
            "ix_research_items_document_visibility",
            "document_id",
            "is_shared",
            "created_at",
        ),
        Index(
            "ix_research_items_project_visibility",
            "project_id",
            "is_shared",
            "created_at",
        ),
        Index(
            "ix_research_items_creator_activity",
            "created_by_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_shared: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )

    created_by: Mapped["AuthUser | None"] = relationship(
        "AuthUser",
        foreign_keys=[created_by_id],
        back_populates="research_items",
    )
    document: Mapped["Document | None"] = relationship("Document")
    project: Mapped["Project | None"] = relationship("Project")
    source_message: Mapped["Message | None"] = relationship(
        "Message",
        back_populates="research_items",
    )
    source_job: Mapped["DurableJob | None"] = relationship("DurableJob")
    highlight_thread: Mapped["HighlightThread | None"] = relationship(
        "HighlightThread",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    citation: Mapped["CitationOutput | None"] = relationship(
        "CitationOutput",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    audio_overview: Mapped["ResearchAudioOverview | None"] = relationship(
        "ResearchAudioOverview",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    data_table: Mapped["ResearchDataTable | None"] = relationship(
        "ResearchDataTable",
        back_populates="item",
        uselist=False,
        cascade="all, delete-orphan",
    )


class HighlightThread(Base):
    __tablename__ = "highlight_threads"

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    quote_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    color: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="blue",
        server_default="blue",
    )
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user",
        server_default="user",
    )
    zotero_annotation_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="highlight_thread",
    )
    comments: Mapped[list["AnnotationComment"]] = relationship(
        "AnnotationComment",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="AnnotationComment.created_at",
    )


class AnnotationComment(Base):
    __tablename__ = "annotation_comments"
    __table_args__ = (
        Index("ix_annotation_comments_thread", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("highlight_threads.research_item_id", ondelete="CASCADE"),
        nullable=False,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="user",
        server_default="user",
    )

    thread: Mapped["HighlightThread"] = relationship(
        "HighlightThread",
        back_populates="comments",
    )
    created_by: Mapped["AuthUser | None"] = relationship(
        "AuthUser",
        foreign_keys=[created_by_id],
        back_populates="annotation_comments",
    )


class CitationOutput(Base):
    __tablename__ = "citation_outputs"

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    snapshot: Mapped[dict[str, JsonValue]] = mapped_column(JSONB, nullable=False)

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="citation",
    )


class ResearchAudioOverview(Base):
    __tablename__ = "research_audio_overviews"

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    transcript: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    s3_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    voice_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_version: Mapped[str] = mapped_column(String(160), nullable=False)

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="audio_overview",
    )


class ResearchDataTable(Base):
    __tablename__ = "research_data_tables"

    research_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("research_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    columns: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    rows: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    citations: Mapped[list[dict[str, JsonValue]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    row_failures: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )

    item: Mapped["ResearchItem"] = relationship(
        "ResearchItem",
        back_populates="data_table",
    )


__all__ = [
    "AnnotationComment",
    "CitationOutput",
    "HighlightThread",
    "ResearchAudioOverview",
    "ResearchDataTable",
    "ResearchItem",
    "ResearchItemKind",
    "ResearchScopeType",
]
