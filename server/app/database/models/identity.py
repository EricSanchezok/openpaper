from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from cloud_auth.models.user import AccountStatus
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .commerce import Onboarding, Subscription
    from .content import (
        Annotation,
        AudioOverviewJob,
        Conversation,
        Highlight,
        LibraryPaper,
        Message,
        Document,
        PaperNote,
        PaperTag,
        PaperUploadJob,
    )
    from .projects import Project, ProjectCollaborator, ProjectInvitation
    from .integrations import (
        ZoteroConnection,
        ZoteroImportedItem,
        ZoteroOAuthPending,
    )


class AuthUser(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[AccountStatus] = mapped_column(String, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile: Mapped["UserProfile | None"] = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    created_documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="creator"
    )
    library_papers: Mapped[list["LibraryPaper"]] = relationship(
        "LibraryPaper", back_populates="user", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="user", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="user", cascade="all, delete-orphan"
    )
    paper_notes: Mapped[list["PaperNote"]] = relationship(
        "PaperNote", back_populates="user", cascade="all, delete-orphan"
    )
    highlights: Mapped[list["Highlight"]] = relationship(
        "Highlight", back_populates="user", cascade="all, delete-orphan"
    )
    annotations: Mapped[list["Annotation"]] = relationship(
        "Annotation", back_populates="user", cascade="all, delete-orphan"
    )
    audio_overview_jobs: Mapped[list["AudioOverviewJob"]] = relationship(
        "AudioOverviewJob", back_populates="user", cascade="all, delete-orphan"
    )
    paper_upload_jobs: Mapped[list["PaperUploadJob"]] = relationship(
        "PaperUploadJob", back_populates="user", cascade="all, delete-orphan"
    )

    # The associated subscription for the user.
    subscription: Mapped["Subscription | None"] = relationship(
        "Subscription",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    onboarding: Mapped["Onboarding | None"] = relationship(
        "Onboarding",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )

    owned_projects: Mapped[list["Project"]] = relationship(
        "Project", foreign_keys="Project.owner_id", back_populates="owner"
    )
    project_collaborations: Mapped[list["ProjectCollaborator"]] = relationship(
        "ProjectCollaborator",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    paper_tags: Mapped[list["PaperTag"]] = relationship(
        "PaperTag", back_populates="user", cascade="all, delete-orphan"
    )
    project_invitations: Mapped[list["ProjectInvitation"]] = relationship(
        "ProjectInvitation",
        back_populates="invited_by",
        cascade="all, delete-orphan",
    )

    zotero_oauth_pending: Mapped[list["ZoteroOAuthPending"]] = relationship(
        "ZoteroOAuthPending",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    zotero_connection: Mapped["ZoteroConnection | None"] = relationship(
        "ZoteroConnection",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    zotero_imported_items: Mapped[list["ZoteroImportedItem"]] = relationship(
        "ZoteroImportedItem",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    locale: Mapped[str | None] = mapped_column(String, nullable=True)
    is_admin: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    user: Mapped[AuthUser] = relationship("AuthUser", back_populates="profile")
