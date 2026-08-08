"""Public Conversation streaming adapter for the single Scholens agent."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Literal

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.product_analytics import track_event
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    ai_limit_app_error,
    enforce_rate_limit,
    release_concurrency,
)
from app.llm.conversation_agent import (
    ConversationAgentResult,
    ScholensConversationAgent,
)
from app.llm.conversation_titles import (
    initial_conversation_title_generator,
    should_generate_initial_title,
)
from app.llm.token_credits import llm_usage_context
from app.modules.conversations.application.contracts.answer_packet import (
    ReferenceBundle,
)
from app.modules.conversations.application.contracts.turns import (
    ConversationAssistantItem,
    ConversationTurnCreateRequest,
    ConversationStreamAssistantItemCompleteEvent,
    ConversationStreamAssistantItemDeltaEvent,
    ConversationStreamAssistantItemStartEvent,
    ConversationStreamCompleteEvent,
    ConversationStreamReferencesEvent,
    ConversationStreamStartEvent,
    ConversationTrace,
)
from app.modules.conversations.infrastructure.chat_streaming import (
    encode_conversation_sse,
    stream_with_stable_error,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.shared.domain import JsonValue
from pydantic import TypeAdapter
from scholens_observability import DiagnosticSnapshotRecorder

logger = logging.getLogger(__name__)
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, JsonValue]])


async def stream_conversation_agent(
    request: ConversationTurnCreateRequest,
    *,
    conversation_id: uuid.UUID,
    client_ip: str,
    executor: ApplicationExecutor[ApplicationCapabilities],
    current_user: Actor,
    runtime: ScholensConversationAgent,
    operation: OperationContext,
    operation_factory: OperationContextFactory,
    generation_kind: Literal["initial", "retry"] = "initial",
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
) -> AsyncGenerator[str, None]:
    """Run one contextual agent and expose its sanitized product event stream."""
    conversation_scope = executor.query(
        lambda capabilities: capabilities.conversation_chat_data.prepare(
            actor=current_user,
            conversation_id=conversation_id,
        )
    )
    project_id = conversation_scope.project_id
    mentions = executor.query(
        lambda capabilities: capabilities.conversation_chat_data.mentions(
            actor=current_user,
            request=request,
        )
    )
    context_snapshot = executor.query(
        lambda capabilities: capabilities.conversation_chat_data.context(
            actor=current_user,
            scope=conversation_scope,
        )
    )

    scope_snapshot: list[dict[str, JsonValue]] = []
    if conversation_scope.paper_context.kind == "library":
        scope_snapshot.append({"kind": "library", "id": "library", "title": "Library"})
    else:
        scope_snapshot.extend(
            {
                "kind": "project",
                "id": str(project.project_id),
                "title": project.title,
            }
            for project in context_snapshot.projects
        )
        scope_snapshot.extend(
            {
                "kind": "paper",
                "id": str(paper.document_id),
                "title": paper.title,
            }
            for paper in context_snapshot.papers
        )
    if mentions.snapshot is not None:
        scope_snapshot.extend(mentions.snapshot)

    formatted_references = (
        {
            "annotations": [],
            "sources": [
                {"key": index, "kind": "user", "reference": reference}
                for index, reference in enumerate(request.user_references, start=1)
            ],
        }
        if request.user_references
        else None
    )
    turn_start = executor.command(
        lambda capabilities: capabilities.conversation_chat_data.start_turn(
            actor=current_user,
            operation=operation,
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            generation_kind=generation_kind,
            user_content=request.user_query,
            user_references=(
                _JSON_OBJECT.validate_python(formatted_references)
                if formatted_references is not None
                else None
            ),
            scope=_JSON_OBJECT_LIST.validate_python(scope_snapshot),
            reasoning_level=request.reasoning_level.value,
            locale=request.locale,
            time_zone=request.time_zone,
        )
    )
    start_event = encode_conversation_sse(
        ConversationStreamStartEvent(
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            response_id=request.response_id,
            variant_index=turn_start.response.variant_index,
            generation_kind=generation_kind,
        )
    )

    if not turn_start.response_created and turn_start.response.status == "completed":
        persisted = turn_start.response

        async def replay_response() -> AsyncGenerator[str, None]:
            sequence = (
                max(
                    (entry.sequence for entry in persisted.trace.entries),
                    default=0,
                )
                + 1
                if persisted.trace is not None
                else 1
            )
            item_id = f"assistant:{request.turn_id}:{sequence}"
            yield start_event
            yield encode_conversation_sse(
                ConversationStreamAssistantItemStartEvent(
                    response_id=persisted.id,
                    item_id=item_id,
                    sequence=sequence,
                )
            )
            yield encode_conversation_sse(
                ConversationStreamAssistantItemDeltaEvent(
                    response_id=persisted.id,
                    item_id=item_id,
                    delta=persisted.content,
                )
            )
            yield encode_conversation_sse(
                ConversationStreamAssistantItemCompleteEvent(
                    response_id=persisted.id,
                    item=ConversationAssistantItem(
                        id=item_id,
                        sequence=sequence,
                        phase="final",
                        content=persisted.content,
                    ),
                )
            )
            if persisted.references is not None:
                yield encode_conversation_sse(
                    ConversationStreamReferencesEvent(
                        response_id=persisted.id,
                        references=persisted.references,
                    )
                )
            yield encode_conversation_sse(
                ConversationStreamCompleteEvent(
                    turn_id=request.turn_id,
                    response_id=persisted.id,
                    trace=persisted.trace,
                )
            )

        return replay_response()
    if not turn_start.response_created:
        raise RuntimeError("Conversation response is already in progress")

    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=client_ip,
            feature="chat",
        )
        concurrency_lease = await acquire_concurrency(
            user_id=int(current_user.id),
            category="interactive",
        )
    except AILimitExceeded as exc:
        raise ai_limit_app_error(
            exc,
            exceeded_message="AI request limit exceeded",
        ) from None

    diagnostic_context: dict[str, object] = {
        "stage": "agent",
        "conversation_id": str(conversation_id),
        "turn_id": str(request.turn_id),
        "scope": conversation_scope.scope_type.value,
        "request": {
            "reasoning_level": request.reasoning_level.value,
            "locale": request.locale,
            "time_zone": request.time_zone,
            "permissions": sorted(
                permission.value for permission in conversation_scope.tool_permissions
            ),
        },
    }

    async def run_response_generator() -> AsyncGenerator[str, None]:
        yield start_event
        final_content = ""
        artifacts: list[dict[str, JsonValue]] = []
        references: ReferenceBundle | None = None
        trace: ConversationTrace | None = None
        started_at = datetime.now(timezone.utc)

        async for event in runtime.stream(
            request=request,
            actor=current_user,
            executor=executor,
            conversation_scope=conversation_scope,
            context_snapshot=context_snapshot,
            conversation_id=conversation_id,
            client_ip=client_ip,
            request_operation=operation,
            correlation_id=turn_start.correlation_id,
            user_operation_id=turn_start.turn_operation_id,
            mentioned_highlights=mentions.highlights,
        ):
            if isinstance(event, ConversationAgentResult):
                trace = event.trace
                artifacts = event.artifacts
                continue
            if isinstance(event, ConversationStreamAssistantItemCompleteEvent):
                if event.item.phase == "final":
                    final_content = event.item.content
            elif isinstance(event, ConversationStreamReferencesEvent):
                references = ReferenceBundle.model_validate(event.references)
            yield encode_conversation_sse(event)

        if not final_content:
            raise RuntimeError("Conversation agent completed without a final answer")

        diagnostic_context["answer_char_count"] = len(final_content)
        diagnostic_context["activity_count"] = (
            sum(entry.kind == "activity" for entry in trace.entries) if trace else 0
        )
        answer_operation = operation_factory.resume(
            correlation_id=turn_start.correlation_id,
            causation_id=turn_start.turn_operation_id,
            initiated_by=OperationInitiator.AGENT,
            origin=operation.origin,
            credential=operation.credential,
        )
        executor.command(
            lambda capabilities: capabilities.conversation_chat_data.complete_turn(
                actor=current_user,
                operation=answer_operation,
                conversation_id=conversation_id,
                turn_id=request.turn_id,
                response_id=request.response_id,
                assistant_content=final_content,
                assistant_references=(
                    _JSON_OBJECT.validate_python(references.model_dump(mode="json"))
                    if references is not None
                    else None
                ),
                assistant_trace=trace,
                artifacts=artifacts,
            )
        )

        history = executor.query(
            lambda capabilities: capabilities.conversation_chat_data.history(
                actor=current_user,
                conversation_id=conversation_id,
                exclude_turn_id=None,
            )
        )
        try:
            if should_generate_initial_title(
                title_is_default=conversation_scope.title_is_default,
                chat_history=history,
            ):
                new_title = initial_conversation_title_generator.generate(history)
            else:
                new_title = None
            if new_title is not None:
                title_operation = operation_factory.resume(
                    correlation_id=turn_start.correlation_id,
                    causation_id=answer_operation.trace.operation_id,
                    initiated_by=OperationInitiator.AGENT,
                    origin=operation.origin,
                    credential=operation.credential,
                )
                executor.command(
                    lambda capabilities: (
                        capabilities.conversations.apply_initial_generated_title(
                            actor=current_user,
                            operation=title_operation,
                            conversation_id=conversation_id,
                            title=new_title,
                        )
                    )
                )
        except Exception:
            logger.exception(
                "conversation.title_generation.failed",
                extra={"conversation_id": str(conversation_id)},
            )

        scope_items = scope_snapshot or []
        track_event(
            "did_chat_message",
            properties={
                "has_user_references": bool(request.user_references),
                "has_references": references is not None,
                "reasoning_level": request.reasoning_level.value,
                "time_taken": (datetime.now(timezone.utc) - started_at).total_seconds(),
                "type": conversation_scope.scope_type.value,
                "project_id": str(project_id) if project_id is not None else None,
                "num_context_papers": sum(
                    item.get("kind") == "paper" for item in scope_items
                ),
                "num_context_projects": sum(
                    item.get("kind") == "project" for item in scope_items
                ),
                "num_mentioned_highlights": sum(
                    item.get("kind") == "highlight" for item in scope_items
                ),
                "uses_library_context": (
                    conversation_scope.paper_context.kind == "library"
                ),
            },
            user_id=str(current_user.id),
        )
        yield encode_conversation_sse(
            ConversationStreamCompleteEvent(
                turn_id=request.turn_id,
                response_id=request.response_id,
                trace=trace,
                artifacts=artifacts,
            )
        )

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(user_id=int(current_user.id), feature="chat"):
                async for event in stream_with_stable_error(
                    run_response_generator(),
                    event_name="conversation_chat_message_error",
                    user_id=current_user.id,
                    properties={
                        "type": conversation_scope.scope_type.value,
                        "conversation_id": str(conversation_id),
                    },
                    diagnostic_recorder=diagnostic_recorder,
                    diagnostic_context=diagnostic_context,
                    response_id=request.response_id,
                ):
                    yield event
        except asyncio.CancelledError:
            executor.command(
                lambda capabilities: (
                    capabilities.conversation_chat_data.finish_response(
                        actor=current_user,
                        conversation_id=conversation_id,
                        response_id=request.response_id,
                        status="cancelled",
                    )
                )
            )
            raise
        except Exception:
            executor.command(
                lambda capabilities: (
                    capabilities.conversation_chat_data.finish_response(
                        actor=current_user,
                        conversation_id=conversation_id,
                        response_id=request.response_id,
                        status="failed",
                    )
                )
            )
            raise
        finally:
            await release_concurrency(concurrency_lease)

    return response_generator()


class DefaultConversationChatGateway:
    """Runs every Conversation scope through the shared agent runtime."""

    def __init__(
        self,
        executor: ApplicationExecutor[ApplicationCapabilities],
        runtime: ScholensConversationAgent,
        operation_factory: OperationContextFactory,
        diagnostic_recorder: DiagnosticSnapshotRecorder,
    ) -> None:
        self._executor = executor
        self._runtime = runtime
        self._operation_factory = operation_factory
        self._diagnostic_recorder = diagnostic_recorder

    async def stream(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        request: ConversationTurnCreateRequest,
        client_ip: str,
        generation_kind: Literal["initial", "retry"] = "initial",
    ) -> AsyncGenerator[str, None]:
        return await stream_conversation_agent(
            request,
            conversation_id=conversation_id,
            client_ip=client_ip,
            executor=self._executor,
            current_user=actor,
            runtime=self._runtime,
            operation=operation,
            operation_factory=self._operation_factory,
            generation_kind=generation_kind,
            diagnostic_recorder=self._diagnostic_recorder,
        )

    async def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        response_id: uuid.UUID,
        client_ip: str,
    ) -> AsyncGenerator[str, None]:
        request = self._executor.query(
            lambda capabilities: capabilities.conversation_chat_data.retry_request(
                actor=actor,
                conversation_id=conversation_id,
                turn_id=turn_id,
                response_id=response_id,
            )
        )
        return await self.stream(
            actor=actor,
            operation=operation,
            conversation_id=conversation_id,
            request=request,
            client_ip=client_ip,
            generation_kind="retry",
        )
