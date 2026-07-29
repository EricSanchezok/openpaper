from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.domain import JsonValue
from app.shared.infrastructure.persistence import Base
from app.shared.domain.enums import ConversationScopeType

if TYPE_CHECKING:
    from app.modules.papers.infrastructure.models import Document
    from app.modules.identity.infrastructure.models import AuthUser
    from app.modules.projects.infrastructure.models import Project
    from app.modules.research.infrastructure.models import ResearchItem


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
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    references: Mapped[dict[str, JsonValue] | None] = mapped_column(
        JSONB, nullable=True
    )
    trace: Mapped[dict[str, JsonValue] | None] = mapped_column(JSONB, nullable=True)
    scope: Mapped[list[dict[str, JsonValue]] | None] = mapped_column(
        JSONB, nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
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
        Index("ix_conversations_user_pinned", "user_id", "pinned_at"),
    )

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
