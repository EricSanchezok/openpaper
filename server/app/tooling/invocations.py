"""Transport-neutral persistence port for write-tool replay."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.shared.domain import JsonValue


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
        operation_id: UUID,
        invocation_key: str,
        tool_name: str,
        arguments_hash: str,
        result: JsonValue,
    ) -> None: ...


__all__ = ["ToolInvocationGateway"]
