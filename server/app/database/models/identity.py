from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from cloud_auth.models.user import AccountStatus
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .commerce import Onboarding, Referral, ReferralCode, Subscription
    from .content import (
        Annotation,
        AudioOverviewJob,
        Conversation,
        Highlight,
        Message,
        Paper,
        PaperNote,
        PaperTag,
        PaperUploadJob,
        ProjectRole,
        ProjectRoleInvitation,
    )
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

    papers: Mapped[list["Paper"]] = relationship(
        "Paper", back_populates="user", cascade="all, delete-orphan"
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

    project_roles: Mapped[list["ProjectRole"]] = relationship(
        "ProjectRole", back_populates="user"
    )
    paper_tags: Mapped[list["PaperTag"]] = relationship(
        "PaperTag", back_populates="user", cascade="all, delete-orphan"
    )
    invitations: Mapped[list["ProjectRoleInvitation"]] = relationship(
        "ProjectRoleInvitation", back_populates="inviter", cascade="all, delete-orphan"
    )

    referral_code: Mapped["ReferralCode | None"] = relationship(
        "ReferralCode",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    referrals_made: Mapped[list["Referral"]] = relationship(
        "Referral",
        foreign_keys="Referral.referrer_user_id",
        back_populates="referrer",
        cascade="all, delete-orphan",
    )
    referral_received: Mapped["Referral | None"] = relationship(
        "Referral",
        foreign_keys="Referral.referee_user_id",
        back_populates="referee",
        uselist=False,
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
    referral_toast_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[AuthUser] = relationship("AuthUser", back_populates="profile")
