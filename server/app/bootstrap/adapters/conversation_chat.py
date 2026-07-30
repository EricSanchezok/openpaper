import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, TypedDict

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.telemetry import track_event
from app.shared.domain import AppError, FailureKind, JsonValue
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency,
)
from app.llm.citation_handler import CitationHandler
from app.llm.conversation_operations import conversation_operations
from app.llm.conversation_agent import conversation_agent_runtime
from app.llm.token_credits import llm_usage_context
from app.modules.conversations.application.contracts.messages import (
    ConversationMessageRequest,
    EvidenceCollection,
)
from app.shared.application import Actor, ApplicationExecutor
from app.modules.conversations.infrastructure.chat_streaming import (
    stream_with_stable_error,
)
from dotenv import load_dotenv
from pydantic import TypeAdapter

load_dotenv()

logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO)

END_DELIMITER = "END_OF_STREAM"
MAX_REASONING_TRACE_CHARS = 100_000
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, JsonValue]])


class EvidenceState(TypedDict):
    evidence: dict[str, Any] | None


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
    evidence_container: EvidenceState,
    artifacts: list[dict[str, object]] | None = None,
    status_messages: list[str] | None = None,
    reasoning_chunks: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """Helper to stream chat chunks and handle common logic."""
    async for chunk in chunk_generator:
        if not isinstance(chunk, dict):
            logger.warning(f"Received unexpected chunk format: {chunk}")
            continue

        chunk_type = chunk.get("type")
        chunk_content = chunk.get("content", "")

        if chunk_type == "artifact":
            if artifacts is not None and isinstance(chunk_content, dict):
                artifacts.append(chunk_content)
            try:
                yield f"{json.dumps({'type': 'artifact', 'content': chunk_content})}{END_DELIMITER}"
            except (TypeError, ValueError) as json_error:
                logger.warning(f"Failed to serialize artifact: {json_error}")
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
            yield f"{json.dumps({'type': 'reasoning', 'content': reasoning_content})}{END_DELIMITER}"
            continue

        if chunk_type == "content":
            text_content = (
                chunk_content if isinstance(chunk_content, str) else str(chunk_content)
            )
            content_chunks.append(text_content)
            try:
                json_response = json.dumps({"type": "content", "content": text_content})
                yield f"{json_response}{END_DELIMITER}"
            except (TypeError, ValueError) as json_error:
                logger.warning(f"Failed to serialize chunk content: {json_error}")
                safe_content = (
                    str(chunk_content).encode("utf-8", errors="replace").decode("utf-8")
                )
                json_response = json.dumps({"type": "content", "content": safe_content})
                yield f"{json_response}{END_DELIMITER}"

        elif chunk_type == "references":
            evidence_container["evidence"] = (
                chunk_content if isinstance(chunk_content, dict) else None
            )
            try:
                json_response = json.dumps(
                    {"type": "references", "content": chunk_content}
                )
                yield f"{json_response}{END_DELIMITER}"
            except (TypeError, ValueError) as json_error:
                logger.warning(f"Failed to serialize references: {json_error}")
                yield f"{json.dumps({'type': 'error', 'content': 'Failed to serialize references'})}{END_DELIMITER}"
        elif chunk_type == "status":
            status_content = (
                chunk_content if isinstance(chunk_content, str) else str(chunk_content)
            )
            _append_status(status_messages, status_content)
            yield f"{json.dumps({'type': 'status', 'content': status_content})}{END_DELIMITER}"


async def stream_conversation_agent(
    request: ConversationMessageRequest,
    *,
    conversation_id: uuid.UUID,
    client_ip: str,
    executor: ApplicationExecutor[ApplicationCapabilities],
    current_user: Actor,
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

    async def run_response_generator() -> AsyncGenerator[str, None]:
        content_chunks: list[str] = []
        artifacts_collected: list[dict[str, object]] = []
        status_messages: list[str] = []
        reasoning_chunks: list[str] = []
        start_time = datetime.now(timezone.utc)
        evidence_container: EvidenceState = {"evidence": None}
        evidence_collection: EvidenceCollection | None = None

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
            scope_snapshot.append(
                {"kind": "library", "id": "library", "title": "Library"}
            )
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

        async for chunk in conversation_agent_runtime.gather_evidence(
            conversation_id=str(conversation_id),
            question=request.user_query,
            current_user=current_user,
            executor=executor,
            conversation_scope=conversation_scope,
        ):
            # Parse the chunk as a dictionary
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type")
                chunk_content = chunk.get("content", "")

                if chunk_type == "evidence_gathered":
                    # Use the EvidenceCollection directly (preserves is_compacted and citation_index)
                    assert isinstance(chunk_content, EvidenceCollection), (
                        "Chunk content must be an EvidenceCollection"
                    )
                    evidence_collection = chunk_content
                elif chunk_type == "status":
                    _append_status(status_messages, chunk_content)
                    yield f"{json.dumps({'type': 'status', 'content': chunk_content})}{END_DELIMITER}"
                else:
                    logger.debug(f"received chunks: {chunk}")

        # Artifacts (e.g. a citation card from find_citation) count as
        # a real outcome — only short-circuit if we have neither.
        anchor_paper = next(
            (
                paper
                for paper in context_snapshot.papers
                if paper.document_id == conversation_scope.document_id
            ),
            None,
        )
        if evidence_collection is None or (
            len(evidence_collection.evidence) == 0
            and len(evidence_collection.artifacts) == 0
            and (anchor_paper is None or not anchor_paper.raw_content)
        ):
            json_response = json.dumps(
                {
                    "type": "content",
                    "content": "It looks like I couldn't find any relevant papers for your question. Please try rephrasing your question. If you think this is an error, please contact support.",
                }
            )
            yield f"{json_response}{END_DELIMITER}"
            return

        yield f"{json.dumps({'type': 'status', 'content': 'Generating response...'})}{END_DELIMITER}"

        chat_generator = conversation_agent_runtime.stream_answer(
            question=request.user_query,
            reasoning_level=request.reasoning_level,
            user_references=request.user_references,
            evidence_gathered=evidence_collection,
            conversation_id=str(conversation_id),
            current_user=current_user,
            all_papers=context_snapshot.papers,
            anchor_paper=anchor_paper,
            context_snapshot=context_snapshot,
            scope_type=conversation_scope.scope_type,
            response_style=request.style,
            mentioned_highlights=mentioned_highlights,
            executor=executor,
        )
        async for stream_chunk in _stream_chat_chunks(
            chunk_generator=chat_generator,
            content_chunks=content_chunks,
            evidence_container=evidence_container,
            artifacts=artifacts_collected,
            status_messages=status_messages,
            reasoning_chunks=reasoning_chunks,
        ):
            yield stream_chunk

        evidence = evidence_container["evidence"]

        # Save the complete message to the database
        full_content = "".join(content_chunks)

        assistant_trace = (
            evidence_collection.to_trace_dict() if evidence_collection else None
        )
        # Fold in the live status messages (the "thinking trace") so it
        # survives reloads, even when there were no tool calls.
        if status_messages:
            assistant_trace = assistant_trace or {}
            assistant_trace["status_messages"] = status_messages
        if reasoning_chunks:
            assistant_trace = assistant_trace or {}
            assistant_trace["reasoning_content"] = "".join(reasoning_chunks)

        # Surface the trajectory live so the just-answered message can show
        # it immediately (it's also persisted for reload below).
        if assistant_trace:
            yield f"{json.dumps({'type': 'trace', 'content': assistant_trace})}{END_DELIMITER}"

        formatted_references = (
            CitationHandler.convert_references_to_dict(
                references=request.user_references
            )
            if request.user_references
            else None
        )

        executor.command(
            lambda capabilities: capabilities.conversation_chat_data.save_turn(
                actor=current_user,
                conversation_id=conversation_id,
                user_content=request.user_query,
                user_references=(
                    _JSON_OBJECT.validate_python(formatted_references)
                    if formatted_references is not None
                    else None
                ),
                scope=(
                    _JSON_OBJECT_LIST.validate_python(scope_snapshot)
                    if scope_snapshot is not None
                    else None
                ),
                assistant_content=full_content,
                assistant_references=(
                    _JSON_OBJECT.validate_python(evidence) if evidence else None
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
            )
        )
        new_title = conversation_operations.generate_title(history)
        if new_title is not None:
            executor.command(
                lambda capabilities: capabilities.conversation_chat_data.rename(
                    actor=current_user,
                    conversation_id=conversation_id,
                    title=new_title,
                )
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
                "has_evidence": bool(evidence),
                "reasoning_level": request.reasoning_level.value,
                "time_taken": (datetime.now(timezone.utc) - start_time).total_seconds(),
                "type": conversation_scope.scope_type.value,
                "project_id": str(project_id) if project_id is not None else None,
                **mention_scope_props,
            },
            user_id=str(current_user.id),
        )

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(
                user_id=int(current_user.id),
                feature="chat",
            ):
                async for event in stream_with_stable_error(
                    run_response_generator(),
                    delimiter=END_DELIMITER,
                    event_name="conversation_chat_message_error",
                    user_id=current_user.id,
                    properties={
                        "type": conversation_scope.scope_type.value,
                        "conversation_id": str(conversation_id),
                    },
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
    ) -> None:
        self._executor = executor

    async def stream(
        self,
        *,
        actor: Actor,
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
        )
