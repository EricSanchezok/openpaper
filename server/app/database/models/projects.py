from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base

if TYPE_CHECKING:
    from .content import AudioOverview, AudioOverviewJob, Conversation, Document
    from .identity import AuthUser


class Project(Base):
    """A lightweight shared paper collection with one explicit owner."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    owner: Mapped["AuthUser"] = relationship(
        "AuthUser", foreign_keys=[owner_id], back_populates="owned_projects"
    )
    collaborators: Mapped[list["ProjectCollaborator"]] = relationship(
        "ProjectCollaborator",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    papers: Mapped[list["ProjectPaper"]] = relationship(
        "ProjectPaper", back_populates="project", cascade="all, delete-orphan"
    )
    invitations: Mapped[list["ProjectInvitation"]] = relationship(
        "ProjectInvitation", back_populates="project", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation",
        back_populates="project",
        foreign_keys="Conversation.project_id",
        passive_deletes=True,
    )
    audio_overviews: Mapped[list["AudioOverview"]] = relationship(
        "AudioOverview",
        cascade="all, delete-orphan",
        primaryjoin=(
            "and_(Project.id == foreign(AudioOverview.conversable_id), "
            "AudioOverview.conversable_type == 'project')"
        ),
        overlaps="audio_overviews",
    )
    audio_overview_jobs: Mapped[list["AudioOverviewJob"]] = relationship(
        "AudioOverviewJob",
        cascade="all, delete-orphan",
        primaryjoin=(
            "and_(Project.id == foreign(AudioOverviewJob.conversable_id), "
            "AudioOverviewJob.conversable_type == 'project')"
        ),
        overlaps="audio_overview_jobs",
    )


class ProjectCollaborator(Base):
    """An accepted collaborator and the three independently delegated powers."""

    __tablename__ = "project_collaborators"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", name="uq_project_collaborator_project_user"
        ),
        Index("ix_project_collaborators_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    can_edit_project: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_manage_papers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_manage_collaborators: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    project: Mapped["Project"] = relationship("Project", back_populates="collaborators")
    user: Mapped["AuthUser"] = relationship(
        "AuthUser", back_populates="project_collaborations"
    )


class ProjectInvitation(Base):
    """A short-lived invitation; only the random token hash is persisted."""

    __tablename__ = "project_invitations"
    __table_args__ = (
        Index("ix_project_invitations_project_email", "project_id", "email"),
        Index("ix_project_invitations_token_hash", "token_hash", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    can_edit_project: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_manage_papers: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    can_manage_collaborators: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped["Project"] = relationship("Project", back_populates="invitations")
    invited_by: Mapped["AuthUser"] = relationship(
        "AuthUser",
        foreign_keys=[invited_by_id],
        back_populates="project_invitations",
    )


class ProjectPaper(Base):
    """A durable project reference that survives the contributor leaving."""

    __tablename__ = "project_papers"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "document_id",
            name="uq_project_papers_project_document",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    added_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="SET NULL"),
        nullable=True,
    )

    project: Mapped["Project"] = relationship("Project", back_populates="papers")
    document: Mapped["Document"] = relationship(
        "Document", back_populates="project_papers"
    )
