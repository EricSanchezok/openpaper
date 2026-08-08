"""Stable error boundary for HTTP streams that have already started."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID, uuid4

from app.database.product_analytics import track_event
from app.modules.conversations.application.contracts.turns import (
    ConversationStreamErrorEvent,
    ConversationStreamEvent,
)
from app.shared.application import ErrorEnvelope
from app.shared.domain import AppError, FailureKind, JsonValue
from scholens_observability import add_counter, current_context, log_event
from scholens_observability import (
    DiagnosticSnapshotRecorder,
    NullDiagnosticSnapshotRecorder,
    build_snapshot,
)

logger = logging.getLogger(__name__)


def encode_conversation_sse(event: ConversationStreamEvent) -> str:
    """Serialize one typed conversation event using the standard SSE wire format."""
    payload = event.model_dump(mode="json")
    return (
        f"event: {event.type}\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def _decode_conversation_sse(event: str) -> dict[str, object] | None:
    data = "\n".join(
        line.removeprefix("data: ")
        for line in event.splitlines()
        if line.startswith("data: ")
    )
    if not data:
        return None
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else None


async def stream_with_stable_error(
    source: AsyncIterator[str],
    *,
    event_name: str,
    user_id: int,
    properties: dict[str, object],
    response_id: UUID,
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
    diagnostic_context: dict[str, object] | None = None,
) -> AsyncIterator[str]:
    """Require one explicit terminal event and preserve stable error semantics."""
    completed = False
    try:
        async for event in source:
            try:
                payload = _decode_conversation_sse(event)
                completed = (
                    isinstance(payload, dict) and payload.get("type") == "complete"
                )
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
        snapshot_id = uuid4()
        public_error = ErrorEnvelope.from_app_error(
            error,
            stage=context.stage or "conversation_stream",
            request_id=context.request_id,
            correlation_id=context.correlation_id,
            diagnostic_id=str(snapshot_id),
        )
        recorder = diagnostic_recorder or NullDiagnosticSnapshotRecorder()
        try:
            recorder.record(
                build_snapshot(
                    snapshot_id=snapshot_id,
                    service=context.service,
                    environment=context.environment,
                    release=context.release,
                    reason="conversation_stream_failed",
                    request_id=context.request_id,
                    operation_id=context.operation_id,
                    correlation_id=context.correlation_id,
                    actor_id=str(user_id),
                    sections={
                        "failure": {
                            "code": error.code,
                            "kind": error.kind.value,
                            "stage": public_error.stage,
                            "exception_type": type(exc).__name__,
                        },
                        "conversation": properties,
                        "runtime": diagnostic_context or {},
                    },
                )
            )
        except Exception as capture_error:
            log_event(
                logger,
                logging.ERROR,
                "diagnostic.snapshot.capture_failed",
                exc_info=capture_error,
                diagnostic_id=str(snapshot_id),
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
        yield encode_conversation_sse(
            ConversationStreamErrorEvent(
                response_id=response_id,
                error=cast(dict[str, JsonValue], public_error.to_dict()),
            )
        )
