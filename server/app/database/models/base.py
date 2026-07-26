from __future__ import annotations

from datetime import datetime
from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class Base(DeclarativeBase):
    metadata = MetaData(schema="scholens")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        identity = getattr(self, "id", None)
        return f"<{self.__class__.__name__} id={identity}>"


# BASIC plans are not considered active subscriptions.
# They are used for users who have not yet subscribed.
