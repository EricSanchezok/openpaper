import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, TypedDict

from app.auth.dependencies import get_required_user
from app.repositories.messages import MessageCreate, message_repository
from app.repositories.documents import document_repository
from app.repositories.project_documents import project_document_repository
from app.database.database import get_db
from app.database.models import (
    ConversationScopeType,
    ReasoningLevel,
)
from app.database.models.base import JsonValue
from app.database.telemetry import track_event
from app.errors import AppError
from app.helpers.ai_limits import (
    AILimitExceeded,
    acquire_concurrency,
    enforce_rate_limit,
    release_concurrency,
)
from app.llm.citation_handler import CitationHandler
from app.llm.conversation_operations import conversation_operations
from app.llm.multi_paper_operations import multi_paper_operations
from app.llm.paper_operations import paper_operations
from app.llm.token_credits import has_token_credits, llm_usage_context
from app.policies.projects import get_project_access
from app.policies.conversations import conversation_policy
from app.repositories.conversations import conversation_repository
from app.repositories.research import research_repository
from app.schemas.message import (
    ChatMessageRequest,
    EvidenceCollection,
    MultiPaperChatRequest,
)
from app.schemas.user import CurrentUser
from app.services.chat_streaming import stream_with_stable_error
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter
from sqlalchemy.orm import Session

load_dotenv()

logger = logging.getLogger(__name__)

logger.setLevel(logging.INFO)

# Create API router with prefix
message_router = APIRouter()

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


@message_router.get("/capabilities")
async def get_chat_capabilities() -> dict[str, object]:
    return {
        "reasoning_levels": [
            {
                "id": "standard",
                "label": "Standard",
                "description": "Fast, balanced reasoning for most questions.",
            },
            {
                "id": "deep",
                "label": "Deep",
                "description": "More thorough reasoning for complex questions.",
            },
        ],
        "default_reasoning_level": ReasoningLevel.STANDARD.value,
    }


def _resolve_mention_scope(
    db: Session,
    current_user: CurrentUser,
    request: "MultiPaperChatRequest",
    *,
    project_id: uuid.UUID | None,
) -> tuple[
    list[str] | None,
    list[dict[str, object]] | None,
    list[dict[str, object]] | None,
]:
    """Resolve @-mentions into (scoped_document_ids, scope_snapshot, highlights).

    - scoped_document_ids: the flat, user-scoped set of paper ids the search is
      hard-limited to — a paper mention contributes itself, a project mention
      contributes all of its papers, a highlight mention contributes its parent
      paper. Used for retrieval scoping.
    - scope_snapshot: a denormalized [{kind, id, title, ...}] of the mentioned
      entities themselves (a project stays a single entry, not its papers),
      persisted on the user message so it renders faithfully later.
    - highlights: [{document_id, highlighted_text, notes}] for the mentioned
      highlights, injected into the answer prompt so the model sees the exact
      attached passages.

    Every id is resolved through a user-scoped CRUD call, so a mention the user
    can't access is silently dropped. All values are None when there are no
    mentions at all (i.e. no scoping should be applied).
    """
    if (
        not request.mentioned_document_ids
        and not request.mentioned_project_ids
        and not request.mentioned_highlight_ids
    ):
        return None, None, None

    scoped: set[str] = set()
    snapshot: list[dict[str, object]] = []

    for document_id in request.mentioned_document_ids or []:
        # In a project chat, resolve via project access (papers may be shared,
        # i.e. not owned by the current user); otherwise resolve by ownership.
        if project_id is not None:
            paper = project_document_repository.get_paper_by_project(
                db,
                document_id=uuid.UUID(document_id),
                project_id=project_id,
                user=current_user,
            )
        else:
            paper = document_repository.find_accessible(
                db, document_id=document_id, user=current_user
            )
        if paper:
            scoped.add(str(paper.id))
            snapshot.append(
                {"kind": "paper", "id": str(paper.id), "title": paper.title}
            )

    for mentioned_project_id in request.mentioned_project_ids or []:
        project_access = get_project_access(
            db,
            project_id=uuid.UUID(mentioned_project_id),
            user_id=current_user.id,
        )
        if project_access is None:
            continue
        project = project_access.project
        document_ids = (
            project_document_repository.get_project_document_ids_by_project_id(
                db, project_id=uuid.UUID(mentioned_project_id), user=current_user
            )
        )
        scoped.update(str(pid) for pid in document_ids)
        snapshot.append(
            {"kind": "project", "id": str(project.id), "title": project.title}
        )

    # Mentioned highlights are grouped by parent paper so each highlighted
    # passage is delivered with that paper's title + abstract for grounding,
    # rather than a bare paper id the model would have to cross-reference.
    highlights_by_paper: dict[str, HighlightGroup] = {}
    for highlight_id in request.mentioned_highlight_ids or []:
        try:
            item = research_repository.get_highlight_thread_visible(
                db,
                thread_id=uuid.UUID(highlight_id),
                user_id=current_user.id,
            )
        except AppError:
            continue
        highlight = item.highlight_thread
        if highlight is None or item.document_id is None:
            continue
        document_id_str = str(item.document_id)
        # The parent paper joins the search scope so it stays searchable.
        scoped.add(document_id_str)

        group = highlights_by_paper.get(document_id_str)
        if group is None:
            paper = document_repository.find_accessible(
                db, document_id=document_id_str, user=current_user
            )
            group = {
                "document_id": document_id_str,
                "paper_title": paper.title if paper else None,
                "paper_abstract": paper.abstract if paper else None,
                "highlights": [],
            }
            highlights_by_paper[document_id_str] = group

        annotation_contents = [
            annotation.content
            for annotation in highlight.comments
            if annotation.content
        ]

        snapshot.append(
            {
                "kind": "highlight",
                "id": str(item.id),
                "title": highlight.quote_text,
                "document_id": document_id_str,
                "paper_title": group["paper_title"],
                "annotations": annotation_contents,
            }
        )

        group["highlights"].append(
            {
                "highlighted_text": highlight.quote_text,
                "page_number": highlight.page_number,
                "annotations": annotation_contents,
            }
        )

    return (
        list(scoped),
        snapshot,
        [dict(group) for group in highlights_by_paper.values()],
    )


@message_router.post("/chat/everything")
async def chat_message_multipaper(
    request: MultiPaperChatRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> StreamingResponse:
    """
    Send a chat message and stream the response from the LLM.

    This searches over the entire corpus of papers and returns a response based on the user's query.
    The response includes both the content and any relevant evidence gathered.
    """
    if not has_token_credits(db, user=current_user):
        raise AppError(
            code="token_quota_exceeded",
            message="Your weekly Token Credits are exhausted",
            status_code=429,
        )
    conversation = conversation_repository.require_owned(
        db,
        conversation_id=uuid.UUID(request.conversation_id),
        user_id=current_user.id,
    )
    conversation_policy.require_can_continue(
        db,
        conversation=conversation,
    )
    if conversation.scope_type not in {
        ConversationScopeType.GLOBAL.value,
        ConversationScopeType.PROJECT.value,
    }:
        raise AppError(
            code="conversation_scope_mismatch",
            message="This conversation cannot be used for a library chat",
            status_code=409,
        )
    project_id = conversation.project_id
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=http_request.client.host if http_request.client else "unknown",
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
            status_code=429,
        ) from None

    async def run_response_generator() -> AsyncGenerator[str, None]:
        content_chunks: list[str] = []
        artifacts_collected: list[dict[str, object]] = []
        status_messages: list[str] = []
        reasoning_chunks: list[str] = []
        start_time = datetime.now(timezone.utc)
        evidence_container: EvidenceState = {"evidence": None}
        evidence_collection: EvidenceCollection | None = None

        # @-mention scoping: resolve mentioned papers/projects/highlights
        # into a flat set of in-scope paper ids (None == no scoping), a
        # denormalized snapshot to persist on the user message, and the
        # highlight passages to inject into the answer.
        (
            scoped_document_ids,
            scope_snapshot,
            mentioned_highlights,
        ) = _resolve_mention_scope(
            db,
            current_user,
            request,
            project_id=project_id,
        )

        async for chunk in multi_paper_operations.gather_evidence(
            conversation_id=request.conversation_id,
            question=request.user_query,
            current_user=current_user,
            db=db,
            project_id=str(project_id) if project_id is not None else None,
            restrict_to_document_ids=scoped_document_ids,
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
        if evidence_collection is None or (
            len(evidence_collection.evidence) == 0
            and len(evidence_collection.artifacts) == 0
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

        if project_id is not None:
            all_papers = project_document_repository.get_all_papers_by_project_id(
                db, project_id=project_id, user=current_user
            )
        else:
            all_papers = document_repository.list_available_library_documents(
                db,
                user=current_user,
            )

        # Keep the answer-generation paper set aligned with the scoped
        # evidence space so citations can't reference out-of-scope papers.
        if scoped_document_ids is not None:
            allowed_ids = set(scoped_document_ids)
            all_papers = [paper for paper in all_papers if str(paper.id) in allowed_ids]

        chat_generator = multi_paper_operations.chat_with_papers(
            question=request.user_query,
            reasoning_level=request.reasoning_level,
            user_references=request.user_references,
            evidence_gathered=evidence_collection,
            conversation_id=request.conversation_id,
            current_user=current_user,
            all_papers=all_papers,
            mentioned_highlights=mentioned_highlights,
            db=db,
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

        # Save user message, with the @-mention scope snapshot attached.
        message_repository.create(
            db,
            request=MessageCreate(
                conversation_id=uuid.UUID(request.conversation_id),
                role="user",
                content=request.user_query,
                references=(
                    _JSON_OBJECT.validate_python(formatted_references)
                    if formatted_references is not None
                    else None
                ),
                scope=(
                    _JSON_OBJECT_LIST.validate_python(scope_snapshot)
                    if scope_snapshot is not None
                    else None
                ),
            ),
            user_id=current_user.id,
        )

        # Save assistant message with content, evidence, and trace.
        # Artifacts go into their own table, linked back via message_id.
        assistant_message = message_repository.create(
            db,
            request=MessageCreate(
                conversation_id=uuid.UUID(request.conversation_id),
                role="assistant",
                content=full_content,
                references=evidence if evidence else None,
                trace=(
                    _JSON_OBJECT.validate_python(assistant_trace)
                    if assistant_trace is not None
                    else None
                ),
            ),
            user_id=current_user.id,
        )

        if assistant_message and artifacts_collected:
            research_repository.create_citations_for_message(
                db,
                conversation=conversation,
                message_id=assistant_message.id,
                user_id=current_user.id,
                snapshots=artifacts_collected,
            )

        # Rename the conversation based on the chat history
        conversation_operations.rename_conversation(
            db=db, conversation_id=request.conversation_id, user=current_user
        )

        # @-mention scoping usage: whether the client asked to scope,
        # what actually resolved (by entity type), and the effective
        # search-space size after resolution.
        scope_items = scope_snapshot or []
        mention_scope_props = {
            "requested_mention_scope": bool(
                request.mentioned_document_ids
                or request.mentioned_project_ids
                or request.mentioned_highlight_ids
            ),
            "used_mention_scope": len(scope_items) > 0,
            "num_mentioned_papers": sum(
                1 for i in scope_items if i.get("kind") == "paper"
            ),
            "num_mentioned_projects": sum(
                1 for i in scope_items if i.get("kind") == "project"
            ),
            "num_mentioned_highlights": sum(
                1 for i in scope_items if i.get("kind") == "highlight"
            ),
            "num_scoped_papers": (
                len(scoped_document_ids) if scoped_document_ids is not None else 0
            ),
        }

        # Track chat message event
        track_event(
            "did_chat_message",
            properties={
                "has_user_references": bool(request.user_references),
                "has_evidence": bool(evidence),
                "reasoning_level": request.reasoning_level.value,
                "time_taken": (datetime.now(timezone.utc) - start_time).total_seconds(),
                "type": conversation.scope_type,
                "project_id": str(project_id) if project_id is not None else None,
                **mention_scope_props,
            },
            user_id=str(current_user.id),
            db=db,
        )

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(
                user_id=int(current_user.id),
                feature="chat_multi_paper",
            ):
                async for event in stream_with_stable_error(
                    run_response_generator(),
                    delimiter=END_DELIMITER,
                    event_name="everything_chat_message_error",
                    user_id=current_user.id,
                    db=db,
                    properties={
                        "type": "everything",
                        "conversation_id": request.conversation_id,
                    },
                ):
                    yield event
        finally:
            await release_concurrency(concurrency_lease)

    return StreamingResponse(response_generator(), media_type="text/event-stream")


@message_router.post("/chat/paper")
async def chat_message_stream(
    request: ChatMessageRequest,
    http_request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_required_user),
) -> StreamingResponse:
    """
    Send a chat message and stream the response from the LLM

    The response style can be:
    - normal: Standard balanced response
    - concise: Short and to the point
    - detailed: Comprehensive and thorough
    """
    if not has_token_credits(db, user=current_user):
        raise AppError(
            code="token_quota_exceeded",
            message="Your weekly Token Credits are exhausted",
            status_code=429,
        )
    conversation = conversation_repository.require_owned(
        db,
        conversation_id=uuid.UUID(request.conversation_id),
        user_id=current_user.id,
    )
    conversation_policy.require_can_continue(
        db,
        conversation=conversation,
    )
    if (
        conversation.scope_type != ConversationScopeType.PAPER.value
        or conversation.document_id is None
    ):
        raise AppError(
            code="conversation_scope_mismatch",
            message="This conversation cannot be used for a paper chat",
            status_code=409,
        )
    document_id = str(conversation.document_id)
    try:
        await enforce_rate_limit(
            user_id=int(current_user.id),
            ip_address=http_request.client.host if http_request.client else "unknown",
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
            status_code=429,
        ) from None

    async def run_response_generator() -> AsyncGenerator[str, None]:
        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        start_time = datetime.now(timezone.utc)
        evidence_container: EvidenceState = {"evidence": None}
        chat_generator = paper_operations.chat_with_paper(
            document_id=document_id,
            conversation_id=request.conversation_id,
            question=request.user_query,
            current_user=current_user,
            reasoning_level=request.reasoning_level,
            user_references=request.user_references,
            response_style=request.style,
            db=db,
        )

        async for chunk in _stream_chat_chunks(
            chunk_generator=chat_generator,
            content_chunks=content_chunks,
            evidence_container=evidence_container,
            reasoning_chunks=reasoning_chunks,
        ):
            yield chunk

        evidence = evidence_container["evidence"]

        # Save the complete message to the database
        full_content = "".join(content_chunks)
        assistant_trace = (
            {"reasoning_content": "".join(reasoning_chunks)}
            if reasoning_chunks
            else None
        )
        if assistant_trace:
            yield f"{json.dumps({'type': 'trace', 'content': assistant_trace})}{END_DELIMITER}"

        formatted_references = (
            CitationHandler.convert_references_to_dict(
                references=request.user_references
            )
            if request.user_references
            else None
        )

        # Save user message
        message_repository.create(
            db,
            request=MessageCreate(
                conversation_id=uuid.UUID(request.conversation_id),
                role="user",
                content=request.user_query,
                references=(
                    _JSON_OBJECT.validate_python(formatted_references)
                    if formatted_references is not None
                    else None
                ),
            ),
            user_id=current_user.id,
        )

        # Save assistant message with both content and evidence
        message_repository.create(
            db,
            request=MessageCreate(
                conversation_id=uuid.UUID(request.conversation_id),
                role="assistant",
                content=full_content,
                references=evidence if evidence else None,
                trace=(
                    _JSON_OBJECT.validate_python(assistant_trace)
                    if assistant_trace is not None
                    else None
                ),
            ),
            user_id=current_user.id,
        )

        # Track chat message event
        track_event(
            "did_chat_message",
            properties={
                "response_style": (request.style.value if request.style else "normal"),
                "has_user_references": bool(request.user_references),
                "has_evidence": bool(evidence),
                "reasoning_level": request.reasoning_level.value,
                "time_taken": (datetime.now(timezone.utc) - start_time).total_seconds(),
                "document_id": document_id,
                "type": "paper",
            },
            user_id=str(current_user.id),
            db=db,
        )

    async def response_generator() -> AsyncGenerator[str, None]:
        try:
            with llm_usage_context(
                user_id=int(current_user.id),
                feature="chat_paper",
            ):
                async for event in stream_with_stable_error(
                    run_response_generator(),
                    delimiter=END_DELIMITER,
                    event_name="chat_message_error",
                    user_id=current_user.id,
                    db=db,
                    properties={
                        "document_id": document_id,
                        "conversation_id": request.conversation_id,
                    },
                ):
                    yield event
        finally:
            await release_concurrency(concurrency_lease)

    return StreamingResponse(response_generator(), media_type="text/event-stream")
