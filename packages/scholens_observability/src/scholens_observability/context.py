"""Explicit request and operation context for logs and traces.

This context is diagnostic metadata only.  It is deliberately separate from
business OperationContext and must never be consulted for authorization.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True, slots=True)
class ObservabilityContext:
    service: str
    environment: str
    release: str | None = None
    request_id: str | None = None
    operation_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    actor_id: str | None = None
    origin: str | None = None
    component: str | None = None
    stage: str | None = None
    conversation_id: str | None = None
    turn_id: str | None = None
    job_id: str | None = None
    task_id: str | None = None

    def fields(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value is not None}


_DEFAULT = ObservabilityContext(service="unknown", environment="development")
_CONTEXT: ContextVar[ObservabilityContext] = ContextVar(
    "scholens_observability_context",
    default=_DEFAULT,
)


def current_context() -> ObservabilityContext:
    return _CONTEXT.get()


def set_context(context: ObservabilityContext) -> Token[ObservabilityContext]:
    return _CONTEXT.set(context)


def reset_context(token: Token[ObservabilityContext]) -> None:
    _CONTEXT.reset(token)


def update_context(**fields: str | None) -> ObservabilityContext:
    updates = {key: value for key, value in fields.items() if value is not None}
    unknown = set(updates).difference(ObservabilityContext.__dataclass_fields__)
    if unknown:
        raise ValueError(f"Unknown observability context fields: {sorted(unknown)}")
    context = replace(current_context(), **updates)
    _CONTEXT.set(context)
    return context


@contextmanager
def bind_context(**fields: str | None) -> Iterator[ObservabilityContext]:
    updates = {key: value for key, value in fields.items() if value is not None}
    context = replace(current_context(), **updates)
    token = set_context(context)
    try:
        yield context
    finally:
        reset_context(token)
