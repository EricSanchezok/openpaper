"""Stable error boundary for HTTP streams that have already started."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from uuid import uuid4

from app.database.telemetry import track_event
from app.shared.application import ErrorEnvelope
from app.shared.domain import AppError, FailureKind
from scholens_observability import add_counter, current_context, log_event

logger = logging.getLogger(__name__)


async def stream_with_stable_error(
    source: AsyncIterator[str],
    *,
    delimiter: str,
    event_name: str,
    user_id: int,
    properties: dict[str, object],
) -> AsyncIterator[str]:
    """Require one explicit terminal event and preserve stable error semantics."""
    completed = False
    try:
        async for event in source:
            try:
                serialized = event[: -len(delimiter)] if event.endswith(delimiter) else event
                payload = json.loads(serialized)
                completed = isinstance(payload, dict) and payload.get("type") == "complete"
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
            yield event
        if not completed:
            raise AppError(
                code="stream_incomplete",
                message="The response stream ended before the operation completed.",
                kind=FailureKind.DEPENDENCY_FAILURE,
                retryable=True,
            )
    except Exception as exc:
        error = (
            exc
            if isinstance(exc, AppError)
            else AppError(
                code="chat_stream_failed",
                message="The response stream failed unexpectedly.",
                kind=FailureKind.DEPENDENCY_FAILURE,
                retryable=True,
            )
        )
        context = current_context()
        public_error = ErrorEnvelope.from_app_error(
            error,
            stage=context.stage or "conversation_stream",
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            diagnostic_id=str(uuid4()),
        )
        track_event(
            event_name,
            properties={
                **properties,
                "error_type": type(exc).__name__,
                "error_code": error.code,
            },
            user_id=str(user_id),
        )
        add_counter(
            "scholens.conversation.stream_errors",
            attributes={"code": error.code, "stage": public_error.stage or "unknown"},
        )
        log_event(
            logger,
            logging.ERROR,
            "conversation.stream.failed",
            exc_info=exc,
            error_code=error.code,
            error_kind=error.kind.value,
            retryable=error.retryable,
            diagnostic_id=public_error.diagnostic_id,
        )
        yield f"{json.dumps({'type': 'error', 'error': public_error.to_dict()})}{delimiter}"
