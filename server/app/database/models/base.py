from __future__ import annotations

from datetime import datetime
from typing import TypeAlias

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class Base(DeclarativeBase):
    metadata = MetaData(schema="scholens")

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        identity = getattr(self, "id", None)
        return f"<{self.__class__.__name__} id={identity}>"

    def to_dict(self) -> dict[str, JsonValue]:
        """
        Convert the SQLAlchemy model instance to a dictionary.
        """

        def _to_json_friendly(value: object) -> JsonValue:
            if isinstance(value, list):
                return [_to_json_friendly(item) for item in value]
            elif isinstance(value, dict):
                return {str(key): _to_json_friendly(val) for key, val in value.items()}
            elif isinstance(value, (str, int, float, bool)):
                return value
            elif value is None:
                return None
            return str(value)

        return {
            column.name: _to_json_friendly(getattr(self, column.name))
            for column in self.__table__.columns
        }


# BASIC plans are not considered active subscriptions.
# They are used for users who have not yet subscribed.
