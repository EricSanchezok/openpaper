"""PostgreSQL adapter for atomic write-tool replay."""

from __future__ import annotations

from uuid import UUID

from app.database.models.tool_invocation import ToolInvocation
from app.shared.domain import AppError, FailureKind, JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session


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
        self._lock(actor_id=actor_id, invocation_key=invocation_key)
        invocation = self._find(
            actor_id=actor_id,
            invocation_key=invocation_key,
        )
        if invocation is None:
            return None
        self._require_same_invocation(
            invocation,
            tool_name=tool_name,
            arguments_hash=arguments_hash,
        )
        return invocation.result

    def _find(
        self,
        *,
        actor_id: int,
        invocation_key: str,
    ) -> ToolInvocation | None:
        return self._session.scalar(
            select(ToolInvocation).where(
                ToolInvocation.actor_id == actor_id,
                ToolInvocation.invocation_key == invocation_key,
            )
        )

    @staticmethod
    def _require_same_invocation(
        invocation: ToolInvocation,
        *,
        tool_name: str,
        arguments_hash: str,
    ) -> None:
        if (
            invocation.tool_name != tool_name
            or invocation.arguments_hash != arguments_hash
        ):
            raise AppError(
                code="tool_invocation_conflict",
                message="This tool invocation key was already used differently",
                kind=FailureKind.CONFLICT,
            )

    def _lock(self, *, actor_id: int, invocation_key: str) -> None:
        """Serialize one actor/key for the duration of the current UoW."""
        lock_key = f"{actor_id}:{invocation_key}"
        self._session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtextextended(lock_key, 0),
                )
            )
        )

    def complete(
        self,
        *,
        actor_id: int,
        operation_id: UUID,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None:
        self._lock(actor_id=actor_id, invocation_key=invocation_key)
        existing = self._find(
            actor_id=actor_id,
            invocation_key=invocation_key,
        )
        if existing is not None:
            self._require_same_invocation(
                existing,
                tool_name=tool_name,
                arguments_hash=arguments_hash,
            )
            return
        self._session.add(
            ToolInvocation(
                actor_id=actor_id,
                operation_id=operation_id,
                invocation_key=invocation_key,
                tool_name=tool_name,
                arguments_hash=arguments_hash,
                status="completed",
                result=result,
            )
        )


__all__ = ["SqlAlchemyToolInvocationGateway"]
