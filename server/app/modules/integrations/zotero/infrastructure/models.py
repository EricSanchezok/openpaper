from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.persistence import Base, JsonValue
from app.shared.domain.enums import ZoteroImportStatus

if TYPE_CHECKING:
    from app.modules.identity.infrastructure.models import AuthUser


class ZoteroOAuthPending(Base):
    __tablename__ = "zotero_oauth_pending"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    oauth_token: Mapped[str] = mapped_column(String, nullable=False, index=True)
    oauth_token_secret: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user: Mapped["AuthUser"] = relationship(
        "AuthUser", back_populates="zotero_oauth_pending"
    )


class ZoteroConnection(Base):
    __tablename__ = "zotero_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    zotero_user_id: Mapped[str] = mapped_column(String, nullable=False)
    api_key: Mapped[str] = mapped_column(String, nullable=False)

    user: Mapped["AuthUser"] = relationship(
        "AuthUser", back_populates="zotero_connection"
    )


class ZoteroImportedItem(Base):
    __tablename__ = "zotero_imported_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    zotero_item_key: Mapped[str] = mapped_column(String, nullable=False)
    zotero_attachment_key: Mapped[str | None] = mapped_column(String, nullable=True)
    import_source: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    upload_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("upload_reservations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default=ZoteroImportStatus.PROCESSING
    )
    annotations_payload: Mapped[list[dict[str, JsonValue]] | None] = mapped_column(
        JSONB, nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "zotero_item_key", name="uq_zotero_import_user_item"
        ),
    )

    user: Mapped["AuthUser"] = relationship(
        "AuthUser", back_populates="zotero_imported_items"
    )
