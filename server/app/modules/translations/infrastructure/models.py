"""Persistence model for user-owned translation preferences."""

from __future__ import annotations

from app.shared.infrastructure.persistence import Base
from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class TranslationPreference(Base):
    __tablename__ = "translation_preferences"
    __table_args__ = (
        CheckConstraint(
            "length(target_language) BETWEEN 2 AND 35 "
            "AND target_language = btrim(target_language)",
            name="ck_translation_preferences_language",
        ),
        CheckConstraint(
            "custom_instructions IS NULL "
            "OR (length(custom_instructions) BETWEEN 1 AND 2000 "
            "AND custom_instructions = btrim(custom_instructions))",
            name="ck_translation_preferences_instructions",
        ),
        {"schema": "scholens"},
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    target_language: Mapped[str] = mapped_column(String(35), nullable=False)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_translate_selection: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
