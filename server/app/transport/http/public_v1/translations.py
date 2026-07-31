"""Cloud-authenticated translation preferences and paper streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import (
    get_application_executor,
    get_translation_workflow,
)
from app.bootstrap.workflows.translation import TranslationWorkflow
from app.modules.translations.application import (
    TranslationPreferencesResponse,
    TranslationPreferencesUpdateRequest,
    TranslationRequest,
    TranslationStreamEvent,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.client_ip import http_client_ip
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

translation_preferences_router = APIRouter(tags=["translations"])
paper_translations_router = APIRouter(tags=["translations"])


class TranslationEventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


@translation_preferences_router.get(
    "/translation-preferences",
    response_model=TranslationPreferencesResponse,
)
def get_translation_preferences(
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> TranslationPreferencesResponse:
    return executor.query(
        lambda capabilities: capabilities.translations.preferences(actor=actor)
    )


@translation_preferences_router.put(
    "/translation-preferences",
    response_model=TranslationPreferencesResponse,
)
def update_translation_preferences(
    request: TranslationPreferencesUpdateRequest,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> TranslationPreferencesResponse:
    return executor.command(
        lambda capabilities: capabilities.translations.update_preferences(
            actor=actor,
            operation=operation,
            request=request,
        )
    )


@paper_translations_router.post(
    "/{document_id}/translations",
    response_class=TranslationEventStreamResponse,
    responses={
        200: {
            "description": "A server-sent stream of translation events.",
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                }
            },
        }
    },
)
async def stream_paper_translation(
    document_id: UUID,
    request: TranslationRequest,
    http_request: Request,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    workflow: TranslationWorkflow = Depends(get_translation_workflow),
) -> TranslationEventStreamResponse:
    events = await workflow.open_stream(
        actor=actor,
        operation=operation,
        document_id=document_id,
        request=request,
        client_ip=http_client_ip(http_request),
    )
    return TranslationEventStreamResponse(
        _sse(events),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse(
    events: AsyncIterator[TranslationStreamEvent],
) -> AsyncIterator[str]:
    async for event in events:
        data = json.dumps(
            event.data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        yield f"event: {event.event}\ndata: {data}\n\n"


__all__ = ["paper_translations_router", "translation_preferences_router"]
