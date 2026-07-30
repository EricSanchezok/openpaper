import asyncio
import json
import logging
import uuid
from contextlib import suppress
from typing import (
    Any,
    AsyncGenerator,
    Iterator,
    Sequence,
)

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.models import ReasoningLevel
from app.llm.citation_handler import CitationHandler
from app.llm.conversation_prompts import scope_system_instructions
from app.llm.evidence_operations import EvidenceOperations
from app.llm.prompts import (
    ANSWER_EVIDENCE_BASED_QUESTION_MESSAGE,
    ANSWER_EVIDENCE_BASED_QUESTION_SYSTEM_PROMPT,
    CONCISE_MODE_INSTRUCTIONS,
    DETAILED_MODE_INSTRUCTIONS,
    NORMAL_MODE_INSTRUCTIONS,
)
from app.llm.backend import StreamChunk, SupplementaryContent, TextContent
from app.modules.conversations.application.chat import (
    ChatPaperSnapshot,
    ConversationContextSnapshot,
)
from app.modules.conversations.application.contracts.messages import (
    EvidenceCollection,
    ResponseStyle,
)
from app.shared.application import Actor, ApplicationExecutor
from app.shared.domain.enums import ConversationScopeType

logger = logging.getLogger(__name__)


class ConversationAgentRuntime(EvidenceOperations):
    """Shared evidence and answer runtime for every conversation entry point."""

    async def stream_answer(
        self,
        conversation_id: str,
        question: str,
        current_user: Actor,
        all_papers: list[ChatPaperSnapshot],
        anchor_paper: ChatPaperSnapshot | None,
        context_snapshot: ConversationContextSnapshot,
        scope_type: ConversationScopeType,
        evidence_gathered: EvidenceCollection,
        executor: ApplicationExecutor[ApplicationCapabilities],
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        user_references: Sequence[str] | None = None,
        mentioned_highlights: list[dict[str, Any]] | None = None,
        response_style: ResponseStyle | None = ResponseStyle.NORMAL,
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Stream the final answer from bounded context and collected evidence."""
        user_citations = (
            CitationHandler.convert_references_to_citations(user_references)
            if user_references
            else None
        )

        casted_conversation_id = uuid.UUID(conversation_id)

        conversation_history = executor.query(
            lambda capabilities: capabilities.conversation_chat_data.history(
                actor=current_user,
                conversation_id=casted_conversation_id,
            )
        )

        formatted_paper_options = {
            str(paper.document_id): str(paper.title) for paper in all_papers
        }

        logger.debug(f"Evidence gathered: {evidence_gathered.get_evidence_dict()}")

        style_instructions = (
            DETAILED_MODE_INSTRUCTIONS
            if response_style is ResponseStyle.DETAILED
            else CONCISE_MODE_INSTRUCTIONS
            if response_style is ResponseStyle.CONCISE
            else NORMAL_MODE_INSTRUCTIONS
        )
        context_guidance = {
            "papers": [
                {
                    "document_id": str(paper.document_id),
                    "title": paper.title,
                    "authors": paper.authors,
                    "keywords": paper.keywords,
                    "publish_date": (
                        paper.publish_date.isoformat()
                        if paper.publish_date is not None
                        else None
                    ),
                }
                for paper in context_snapshot.papers
            ],
            "projects": [
                {
                    "project_id": str(project.project_id),
                    "title": project.title,
                    "description": project.description,
                    "document_count": project.document_count,
                }
                for project in context_snapshot.projects
            ],
            "available_document_count": context_snapshot.available_document_count,
        }
        formatted_system_prompt = (
            ANSWER_EVIDENCE_BASED_QUESTION_SYSTEM_PROMPT.format(
                available_papers=formatted_paper_options,
            )
            + style_instructions
            + scope_system_instructions(scope_type)
        )

        formatted_prompt = ANSWER_EVIDENCE_BASED_QUESTION_MESSAGE.format(
            question=f"{question}\n\n{user_citations}" if user_citations else question,
        )

        evidence_buffer: list[str] = []
        text_buffer: str = ""
        in_evidence_section = False

        START_DELIMITER = "---EVIDENCE---"
        END_DELIMITER = "---END-EVIDENCE---"

        # Build multipart message: supplementary evidence + user question
        message_content: list[TextContent | SupplementaryContent] = [
            SupplementaryContent(
                content=json.dumps(context_guidance, indent=2),
                label="conversation_context",
            ),
            SupplementaryContent(
                content=json.dumps(evidence_gathered.get_evidence_dict(), indent=2),
                label="collected_evidence",
            ),
            TextContent(text=formatted_prompt),
        ]
        if anchor_paper is not None and anchor_paper.raw_content:
            message_content.insert(
                0,
                SupplementaryContent(
                    content=anchor_paper.raw_content,
                    label="anchor_paper_full_text",
                ),
            )

        # @-mentioned highlights are exact passages the user attached to ground
        # this question. Inject them directly so the answer model always sees
        # them, regardless of what evidence gathering happened to retrieve.
        if mentioned_highlights:
            message_content.insert(
                0,
                SupplementaryContent(
                    content=json.dumps(mentioned_highlights, indent=2),
                    label="mentioned_highlights",
                ),
            )

        # Surface any citation artifacts produced during evidence gathering as
        # first-party cards, and give the answer model the resolved data so it
        # can reference (but not re-paste) them.
        citation_artifacts = evidence_gathered.get_artifacts()
        if citation_artifacts:
            artifact_payloads = [
                {
                    "kind": "citation",
                    "document_id": artifact.document_id,
                    "preferred_style": artifact.preferred_style,
                    "style_display": artifact.style_display,
                    "data": artifact.data.model_dump(),
                    "method": artifact.method,
                    "missing_fields": artifact.missing_fields,
                    "confidence": artifact.confidence,
                }
                for artifact in citation_artifacts
            ]
            message_content.insert(
                1,
                SupplementaryContent(
                    content=json.dumps(artifact_payloads, indent=2),
                    label="resolved_citations",
                ),
            )
            for payload in artifact_payloads:
                yield {"type": "artifact", "content": payload}

        queue: asyncio.Queue[StreamChunk | dict[str, str] | None] = asyncio.Queue()

        async def pinger() -> None:
            """Yields a status message every 5 seconds to keep the connection alive."""
            with suppress(asyncio.CancelledError):
                while True:
                    await queue.put(
                        {"type": "status", "content": "Finalizing thoughts..."}
                    )
                    await asyncio.sleep(5)

        async def stream_reader() -> None:
            """Reads from the LLM stream and puts chunks into the queue."""

            def get_next_chunk(
                iterator: Iterator[StreamChunk],
            ) -> StreamChunk | None:
                try:
                    return next(iterator)
                except StopIteration:
                    return None

            try:
                blocking_iterator = self.send_message_stream(
                    message=message_content,
                    system_prompt=formatted_system_prompt,
                    history=conversation_history,
                    reasoning_level=reasoning_level,
                )
                while True:
                    chunk = await asyncio.to_thread(get_next_chunk, blocking_iterator)
                    if chunk is None:
                        break
                    await queue.put(chunk)
            finally:
                await queue.put(None)

        pinger_task = asyncio.create_task(pinger())
        stream_reader_task = asyncio.create_task(stream_reader())

        first_chunk_received = False

        try:
            while True:
                item = await queue.get()
                if item is None:  # Stream is done
                    break

                if isinstance(item, dict):
                    yield item
                    continue

                if not first_chunk_received:
                    pinger_task.cancel()
                    first_chunk_received = True

                chunk = item
                if chunk.thinking:
                    yield {"type": "reasoning", "content": chunk.thinking}
                text = chunk.text

                logger.debug(f"Received chunk: {text}")

                if not text:
                    continue

                text_buffer += text

                if not in_evidence_section and START_DELIMITER in text_buffer:
                    in_evidence_section = True
                    pre_evidence = text_buffer.split(START_DELIMITER)[0]
                    if pre_evidence:
                        yield {"type": "content", "content": pre_evidence}
                    evidence_buffer = [text_buffer.split(START_DELIMITER)[1]]
                    text_buffer = ""
                    continue

                reconstructed_buffer = "".join(evidence_buffer + [text_buffer]).strip()

                if in_evidence_section and END_DELIMITER in reconstructed_buffer:
                    delimiter_pos = reconstructed_buffer.find(END_DELIMITER)
                    evidence_part = reconstructed_buffer[:delimiter_pos]
                    remaining = reconstructed_buffer[
                        delimiter_pos + len(END_DELIMITER) :
                    ]

                    structured_evidence = CitationHandler.parse_evidence_block(
                        evidence_part
                    )

                    # Resolve compacted citations to original snippets if evidence was compacted
                    if evidence_gathered.is_compacted:
                        structured_evidence = (
                            CitationHandler.resolve_compacted_citations(
                                structured_evidence,
                                evidence_gathered.citation_index,
                            )
                        )

                    yield {
                        "type": "references",
                        "content": {
                            "citations": structured_evidence,
                        },
                    }

                    in_evidence_section = False
                    evidence_buffer = []
                    text_buffer = remaining

                    if remaining:
                        yield {"type": "content", "content": remaining}
                    continue

                if in_evidence_section:
                    evidence_buffer.append(text)
                    text_buffer = ""
                else:
                    if len(text_buffer) > len(START_DELIMITER) * 2:
                        to_yield = text_buffer[: -len(START_DELIMITER)]
                        yield {"type": "content", "content": to_yield}
                        text_buffer = text_buffer[-len(START_DELIMITER) :]
        finally:
            if not pinger_task.done():
                pinger_task.cancel()
            if not stream_reader_task.done():
                stream_reader_task.cancel()

        # Check if stream_reader_task raised an exception
        if stream_reader_task.done():
            exc = stream_reader_task.exception()
            if exc is not None:
                logger.error(f"Stream reader task failed with exception: {exc}")
                yield {
                    "type": "error",
                    "content": "Sorry, an error occurred while working on this response. Please try again.",
                }
                return

        # Handle case where stream ended while still in evidence section
        if in_evidence_section and evidence_buffer:
            reconstructed_buffer = "".join(evidence_buffer + [text_buffer]).strip()
            logger.warning(
                "Stream ended while in evidence section without END_DELIMITER"
            )

            if reconstructed_buffer:
                try:
                    structured_evidence = CitationHandler.parse_evidence_block(
                        reconstructed_buffer
                    )

                    # Resolve compacted citations to original snippets if evidence was compacted
                    if evidence_gathered.is_compacted:
                        structured_evidence = (
                            CitationHandler.resolve_compacted_citations(
                                structured_evidence,
                                evidence_gathered.citation_index,
                            )
                        )

                    yield {
                        "type": "references",
                        "content": {
                            "citations": structured_evidence,
                        },
                    }
                except Exception as e:
                    logger.error(f"Failed to parse incomplete evidence block: {e}")
                    yield {"type": "content", "content": reconstructed_buffer}

            text_buffer = ""

        # Yield any remaining text buffer content
        if text_buffer:
            yield {"type": "content", "content": text_buffer}


conversation_agent_runtime = ConversationAgentRuntime()
