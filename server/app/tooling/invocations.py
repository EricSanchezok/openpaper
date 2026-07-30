"""Persistent replay ledger for model-initiated write operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol

from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.infrastructure.persistence import Base
from sqlalchemy import (
    UUID,
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.sql import func


class ToolInvocation(Base):
    __tablename__ = "tool_invocations"
    __table_args__ = (
        UniqueConstraint(
            "actor_id",
            "invocation_key",
            name="uq_tool_invocations_actor_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    invocation_key: Mapped[str] = mapped_column(String(512), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[JsonValue] = mapped_column(JSONB, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ToolInvocationGateway(Protocol):
    def replay(
        self,
        *,
        actor_id: int,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
    ) -> JsonValue | None: ...

    def complete(
        self,
        *,
        actor_id: int,
        invocation_key: str,
        source: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None: ...


class SqlAlchemyToolInvocationGateway:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replay(
        self,
        *,
        actor_id: int,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
    ) -> JsonValue | None:
        invocation = self._session.scalar(
            select(ToolInvocation).where(
                ToolInvocation.actor_id == actor_id,
                ToolInvocation.invocation_key == invocation_key,
            )
        )
        if invocation is None:
            return None
        if (
            invocation.tool_name != tool_name
            or invocation.arguments_hash != arguments_hash
        ):
            raise AppError(
                code="tool_invocation_conflict",
                message="This tool invocation key was already used differently",
                kind=FailureKind.CONFLICT,
            )
        return invocation.result

    def complete(
        self,
        *,
        actor_id: int,
        invocation_key: str,
        source: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None:
        self._session.add(
            ToolInvocation(
                actor_id=actor_id,
                invocation_key=invocation_key,
                source=source,
                tool_name=tool_name,
                arguments_hash=arguments_hash,
                result=result,
            )
        )
