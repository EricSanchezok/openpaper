"""Persistence for user-owned external Connector credentials."""

from __future__ import annotations

from datetime import datetime

from app.shared.infrastructure.persistence import Base
from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column


class ConnectorConnection(Base):
    __tablename__ = "connector_connections"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('anysearch', 'tavily', 'exa', 'firecrawl')",
            name="ck_connector_connections_provider",
        ),
        {"schema": "scholens"},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    credential_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
