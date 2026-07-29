from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from app.shared.infrastructure.persistence import Base
from sqlalchemy import UUID, BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.modules.identity.infrastructure.models import AuthUser


class Onboarding(Base):
    __tablename__ = "onboarding"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    company: Mapped[str | None] = mapped_column(String, nullable=True)
    research_fields: Mapped[str | None] = mapped_column(String, nullable=True)
    research_fields_other: Mapped[str | None] = mapped_column(String, nullable=True)
    job_titles: Mapped[str | None] = mapped_column(String, nullable=True)
    job_titles_other: Mapped[str | None] = mapped_column(String, nullable=True)
    reading_frequency: Mapped[str | None] = mapped_column(String, nullable=True)

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="onboarding")
