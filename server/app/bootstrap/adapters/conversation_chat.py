import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, TypedDict

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.product_analytics import track_event
from app.shared.domain import AppError, FailureKind, JsonValue
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency,
)
from app.llm.conversation_operations import conversation_operations
from app.llm.conversation_agent import ConversationAgentRuntime
from app.llm.token_credits import llm_usage_context
from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
    ConversationStreamCompleteEvent,
    ConversationStreamContentDeltaEvent,
    ConversationStreamReasoningEvent,
    ConversationStreamReferencesEvent,
    ConversationStreamStartEvent,
    ConversationStreamStatusEvent,
    ToolRunState,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.modules.conversations.infrastructure.chat_streaming import (
    encode_conversation_sse,
    stream_with_stable_error,
)
from dotenv import load_dotenv
from pydantic import TypeAdapter
from scholens_observability import DiagnosticSnapshotRecorder

load_dotenv()

logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO)

MAX_REASONING_TRACE_CHARS = 100_000
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, JsonValue]])


class ReferencesState(TypedDict):
    references: dict[str, Any] | None


class HighlightGroup(TypedDict):
    document_id: str
    paper_title: str | None
    paper_abstract: str | None
    highlights: list[dict[str, object]]


def _append_status(messages: list[str] | None, message: str) -> None:
    """Append a status message, collapsing consecutive duplicates (e.g. heartbeats)."""
    if messages is None or not message:
        return
    if not messages or messages[-1] != message:
        messages.append(message)


async def _stream_chat_chunks(
    chunk_generator: AsyncGenerator[dict[str, object] | str, None],
    content_chunks: list[str],
    references_container: ReferencesState,
    artifacts: list[dict[str, object]] | None = None,
    status_messages: list[str] | None = None,
    reasoning_chunks: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """Helper to stream chat chunks and handle common logic."""
    async for chunk in chunk_generator:
        if not isinstance(chunk, dict):
            logger.warning(
                "conversation.stream.invalid_chunk",
                extra={"chunk_type": type(chunk).__name__},
            )
            continue

        chunk_type = chunk.get("type")
        chunk_content = chunk.get("content", "")

        if chunk_type == "artifact":
            if artifacts is not None and isinstance(chunk_content, dict):
                artifacts.append(chunk_content)
            # Artifacts are persisted and delivered with the terminal event so
            # the public stream remains a small, stable event union.
            continue

        if chunk_type == "reasoning":
            reasoning_content = (
                chunk_content if isinstance(chunk_content, str) else str(chunk_content)
            )
            if reasoning_chunks is not None and reasoning_content:
                remaining = MAX_REASONING_TRACE_CHARS - sum(
                    len(part) for part in reasoning_chunks
                )
                if remaining > 0:
                    reasoning_chunks.append(reasoning_content[:remaining])
            yield encode_conversation_sse(
                ConversationStreamReasoningEvent(delta=reasoning_content)
            )
            continue

        if chunk_type == "content":
            text_content = (
                chunk_content if isinstance(chunk_content, str) else str(chunk_content)
            )
            content_chunks.append(text_content)
            try:
                yield encode_conversation_sse(
                    ConversationStreamContentDeltaEvent(delta=text_content)
                )
            except (TypeError, ValueError) as json_error:
                logger.warning(
                    "conversation.stream.content_repaired",
                    extra={"error_type": type(json_error).__name__},
                )
                safe_content = (
                    str(chunk_content).encode("utf-8", errors="replace").decode("utf-8")
                )
                yield encode_conversation_sse(
                    ConversationStreamContentDeltaEvent(delta=safe_content)
                )

        elif chunk_type == "references":
            references_container["references"] = (
                chunk_content if isinstance(chunk_content, dict) else None
            )
            try:
                if isinstance(chunk_content, dict):
                    yield encode_conversation_sse(
                        ConversationStreamReferencesEvent(
                            references=_JSON_OBJECT.validate_python(chunk_content)
                        )
                    )
            except (TypeError, ValueError) as json_error:
                raise AppError(
                    code="stream_serialization_failed",
                    message="Response references could not be serialized.",
                    kind=FailureKind.INTERNAL,
                    retryable=False,
                ) from json_error
        elif chunk_type == "status":
            status_content = (
                chunk_content if isinstance(chunk_content, str) else str(chunk_content)
            )
            _append_status(status_messages, status_content)
            yield encode_conversation_sse(
                ConversationStreamStatusEvent(message=status_content)
            )
        elif chunk_type == "error":
            raise AppError(
                code="agent_runtime_failed",
                message="The agent runtime could not complete this response.",
                kind=FailureKind.DEPENDENCY_FAILURE,
                retryable=True,
            )


async def stream_conversation_agent(
    request: ConversationMessageRequest,
    *,
    conversation_id: uuid.UUID,
    client_ip: str,
    executor: ApplicationExecutor[ApplicationCapabilities],
    current_user: Actor,
    runtime: ConversationAgentRuntime,
    operation: OperationContext,
    operation_factory: OperationContextFactory,
    diagnostic_recorder: DiagnosticSnapshotRecorder | None = None,
) -> AsyncGenerator[str, None]:
    """
    Send a chat message and stream the response from the LLM.

    Search and read within the Conversation's server-bound paper context, then
    stream one cited answer through the shared runtime.
    """
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
    mentioned_highlights = mentions.highlights
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
    if mentions.snapshot:
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
            user_content=request.user_query,
            user_references=(
                _JSON_OBJECT.validate_python(formatted_references)
                if formatted_references is not None
                else None
            ),
            scope=_JSON_OBJECT_LIST.validate_python(scope_snapshot),
        )
    )

    start_event = encode_conversation_sse(
        ConversationStreamStartEvent(
            conversation_id=conversation_id,
            turn_id=request.turn_id,
        )
    )

    if turn_start.assistant is not None:
        persisted = turn_start.assistant

        async def replay_response() -> AsyncGenerator[str, None]:
            yield start_event
            yield encode_conversation_sse(
                ConversationStreamContentDeltaEvent(delta=persisted.content)
            )
            if persisted.references is not None:
                yield encode_conversation_sse(
                    ConversationStreamReferencesEvent(references=persisted.references)
                )
            yield encode_conversation_sse(
                ConversationStreamCompleteEvent(
                    turn_id=request.turn_id,
                    trace=persisted.trace,
                )
            )

        return replay_response()

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
        raise AppError(
            code=exc.code,
            message="AI request limit exceeded",
            kind=FailureKind.RATE_LIMITED,
        ) from None

    diagnostic_context: dict[str, object] = {
        "stage": "tool_loop",
        "conversation_id": str(conversation_id),
        "turn_id": str(request.turn_id),
        "scope": conversation_scope.scope_type.value,
        "request": {
            "user_query": request.user_query,
            "reasoning_level": request.reasoning_level.value,
            "permissions": sorted(
                permission.value for permission in conversation_scope.tool_permissions
            ),
        },
    }

    async def run_response_generator() -> AsyncGenerator[str, None]:
        yield start_event
        content_chunks: list[str] = []
        artifacts_collected: list[dict[str, object]] = []
        status_messages: list[str] = []
        reasoning_chunks: list[str] = []
        start_time = datetime.now(timezone.utc)
        references_container: ReferencesState = {"references": None}
        tool_state: ToolRunState | None = None

        async for chunk in runtime.run_tools(
            conversation_id=conversation_id,
            turn_id=request.turn_id,
            client_ip=client_ip,
            question=request.user_query,
            current_user=current_user,
            executor=executor,
            conversation_scope=conversation_scope,
            request_operation=operation,
            turn_correlation_id=turn_start.correlation_id,
            user_operation_id=turn_start.user_operation_id,
        ):
            # Parse the chunk as a dictionary
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                chunk_content = chunk.get("content", "")

                if chunk_type == "tool_run_completed":
                    assert isinstance(chunk_content, ToolRunState), (
                        "Chunk content must be a ToolRunState"
                    )
                    tool_state = chunk_content
                elif chunk_type == "status":
                    status_content = str(chunk_content)
                    _append_status(status_messages, status_content)
                    yield encode_conversation_sse(
                        ConversationStreamStatusEvent(message=status_content)
                    )
                else:
                    logger.warning(
                        "conversation.runtime.unknown_chunk",
                        extra={"chunk_type": str(chunk_type)},
                    )

        diagnostic_context["stage"] = "answer_preparation"
        if tool_state is not None:
            diagnostic_context["tool_trace"] = tool_state.to_trace_dict()

        # Artifacts and completed actions are real outcomes. Only short-circuit
        # when the loop and the paper anchor supplied no usable information.
        anchor_paper = next(
            (
                paper
                for paper in context_snapshot.papers
                if paper.document_id == conversation_scope.document_id
            ),
            None,
        )
        lacks_answer_context = tool_state is None or (
            not tool_state.has_answer_material()
            and len(tool_state.artifacts) == 0
            and len(tool_state.action_results) == 0
            and (anchor_paper is None or not anchor_paper.raw_content)
            and not mentioned_highlights
            and not request.user_references
        )
        if lacks_answer_context:
            no_results_message = (
                "It looks like I couldn't find any relevant papers for your "
                "question. Please try rephrasing your question. If you think "
                "this is an error, please contact support."
            )
            content_chunks.append(no_results_message)
            yield encode_conversation_sse(
                ConversationStreamContentDeltaEvent(delta=no_results_message)
            )
        else:
            assert tool_state is not None
            diagnostic_context["stage"] = "final_answer"
            yield encode_conversation_sse(
                ConversationStreamStatusEvent(message="Generating response...")
            )

            chat_generator = runtime.stream_answer(
                question=request.user_query,
                reasoning_level=request.reasoning_level,
                user_references=request.user_references,
                tool_state=tool_state,
                conversation_id=str(conversation_id),
                turn_id=request.turn_id,
                current_user=current_user,
                all_papers=context_snapshot.papers,
                anchor_paper=anchor_paper,
                context_snapshot=context_snapshot,
                scope_type=conversation_scope.scope_type,
                mentioned_highlights=mentioned_highlights,
                executor=executor,
            )
            async for stream_chunk in _stream_chat_chunks(
                chunk_generator=chat_generator,
                content_chunks=content_chunks,
                references_container=references_container,
                artifacts=artifacts_collected,
                status_messages=status_messages,
                reasoning_chunks=reasoning_chunks,
            ):
                yield stream_chunk

        references = references_container["references"]

        # Save the complete message to the database
        full_content = "".join(content_chunks)
        diagnostic_context["answer_char_count"] = len(full_content)

        assistant_trace = tool_state.to_trace_dict() if tool_state else None
        # Fold in the live status messages (the "thinking trace") so it
        # survives reloads, even when there were no tool calls.
        if status_messages:
            assistant_trace = assistant_trace or {}
            assistant_trace["status_messages"] = status_messages
        if reasoning_chunks:
            assistant_trace = assistant_trace or {}
            assistant_trace["reasoning_content"] = "".join(reasoning_chunks)

        answer_operation = operation_factory.resume(
            correlation_id=turn_start.correlation_id,
            causation_id=turn_start.user_operation_id,
            initiated_by=OperationInitiator.AGENT,
            origin=operation.origin,
            credential=operation.credential,
        )

        diagnostic_context["stage"] = "persist"
        executor.command(
            lambda capabilities: capabilities.conversation_chat_data.complete_turn(
                actor=current_user,
                operation=answer_operation,
                conversation_id=conversation_id,
                turn_id=request.turn_id,
                assistant_content=full_content,
                assistant_references=(
                    _JSON_OBJECT.validate_python(references) if references else None
                ),
                assistant_trace=(
                    _JSON_OBJECT.validate_python(assistant_trace)
                    if assistant_trace is not None
                    else None
                ),
                artifacts=_JSON_OBJECT_LIST.validate_python(artifacts_collected),
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
            new_title = conversation_operations.generate_title(history)
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
                        capabilities.conversations.apply_generated_title(
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
        mention_scope_props = {
            "num_context_papers": sum(
                1 for i in scope_items if i.get("kind") == "paper"
            ),
            "num_context_projects": sum(
                1 for i in scope_items if i.get("kind") == "project"
            ),
            "num_mentioned_highlights": sum(
                1 for i in scope_items if i.get("kind") == "highlight"
            ),
            "uses_library_context": conversation_scope.paper_context.kind == "library",
        }

        # Track chat message event
        track_event(
            "did_chat_message",
            properties={
                "has_user_references": bool(request.user_references),
                "has_references": bool(references),
                "reasoning_level": request.reasoning_level.value,
                "time_taken": (datetime.now(timezone.utc) - start_time).total_seconds(),
                "type": conversation_scope.scope_type.value,
                "project_id": str(project_id) if project_id is not None else None,
                **mention_scope_props,
            },
            user_id=str(current_user.id),
        )
        yield encode_conversation_sse(
            ConversationStreamCompleteEvent(
                turn_id=request.turn_id,
                trace=(
                    _JSON_OBJECT.validate_python(assistant_trace)
                    if assistant_trace is not None
                    else None
                ),
                artifacts=_JSON_OBJECT_LIST.validate_python(artifacts_collected),
            )
        )

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(
                user_id=int(current_user.id),
                feature="chat",
            ):
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
                ):
                    yield event
        finally:
            await release_concurrency(concurrency_lease)

    return response_generator()


class DefaultConversationChatGateway:
    """Runs every Conversation scope through the shared agent runtime."""

    def __init__(
        self,
        executor: ApplicationExecutor[ApplicationCapabilities],
        runtime: ConversationAgentRuntime,
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
        request: ConversationMessageRequest,
        client_ip: str,
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
            diagnostic_recorder=self._diagnostic_recorder,
        )
