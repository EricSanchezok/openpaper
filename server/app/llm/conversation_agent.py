import asyncio
import logging
import uuid
from contextlib import suppress
from typing import (
    Any,
    AsyncGenerator,
    Sequence,
)

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.models import ReasoningLevel
from app.llm.answer_packet import AnswerPacketBuilder
from app.llm.conversation_prompts import final_answer_role_instructions
from app.llm.conversation_tool_loop import ConversationToolLoop
from app.llm.grounded_answer import GroundedAnswerStreamParser
from app.llm.prompts import (
    CONVERSATION_ANSWER_MESSAGE,
    CONVERSATION_ANSWER_SYSTEM_PROMPT,
)
from app.llm.backend import StreamChunk, SupplementaryContent, TextContent
from app.llm.streaming import iterate_in_thread
from app.llm.errors import classify_llm_error
from app.modules.conversations.application.chat import (
    ChatPaperSnapshot,
    ConversationContextSnapshot,
)
from app.modules.conversations.application.contracts.messages import ToolRunState
from app.shared.application import Actor, ApplicationExecutor
from app.shared.domain import AppError, JsonValue
from app.shared.domain.enums import ConversationScopeType
from app.tooling import DocumentSourceCandidate
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class ConversationAgentRuntime(ConversationToolLoop):
    """Shared evidence and answer runtime for every conversation entry point."""

    async def stream_answer(
        self,
        conversation_id: str,
        turn_id: uuid.UUID,
        question: str,
        current_user: Actor,
        all_papers: list[ChatPaperSnapshot],
        anchor_paper: ChatPaperSnapshot | None,
        context_snapshot: ConversationContextSnapshot,
        scope_type: ConversationScopeType,
        tool_state: ToolRunState,
        executor: ApplicationExecutor[ApplicationCapabilities],
        reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD,
        user_references: Sequence[str] | None = None,
        mentioned_highlights: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[str | dict[str, Any], None]:
        """Stream one answer from a bounded, server-validated AnswerPacket."""

        casted_conversation_id = uuid.UUID(conversation_id)

        conversation_history = executor.query(
            lambda capabilities: capabilities.conversation_chat_data.history(
                actor=current_user,
                conversation_id=casted_conversation_id,
                exclude_turn_id=turn_id,
            )
        )

        formatted_paper_options = {
            str(paper.document_id): str(paper.title) for paper in all_papers
        }

        logger.debug(
            "conversation.tool_run.completed",
            extra={"tool_call_count": len(tool_state.tool_calls)},
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
        formatted_prompt = CONVERSATION_ANSWER_MESSAGE.format(
            question=question,
        )

        # Surface any citation artifacts produced during evidence gathering as
        # first-party cards, and give the answer model the resolved data so it
        # can reference (but not re-paste) them.
        citation_artifacts = tool_state.get_artifacts()
        artifact_payloads: list[dict[str, JsonValue]] = []
        if citation_artifacts:
            raw_artifact_payloads: list[JsonValue] = [
                _JSON_VALUE.validate_python(
                    {
                        "kind": "citation",
                        "document_id": artifact.document_id,
                        "preferred_style": artifact.preferred_style,
                        "style_display": artifact.style_display,
                        "data": artifact.data.model_dump(mode="json"),
                        "method": artifact.method,
                        "missing_fields": artifact.missing_fields,
                        "confidence": artifact.confidence,
                    }
                )
                for artifact in citation_artifacts
            ]
            artifact_payloads = [
                value for value in raw_artifact_payloads if isinstance(value, dict)
            ]
            for payload in artifact_payloads:
                yield {"type": "artifact", "content": payload}

        direct_sources: list[DocumentSourceCandidate] = []
        if anchor_paper is not None and anchor_paper.raw_content:
            direct_sources.append(
                DocumentSourceCandidate(
                    document_id=anchor_paper.document_id,
                    excerpt=anchor_paper.raw_content,
                    title=anchor_paper.title,
                    authors=tuple(anchor_paper.authors or ()),
                    locator={"origin": "anchor_paper"},
                )
            )
        for group in mentioned_highlights or []:
            try:
                document_id = uuid.UUID(str(group["document_id"]))
            except (KeyError, TypeError, ValueError):
                continue
            title = group.get("paper_title")
            for highlight in group.get("highlights", []):
                if not isinstance(highlight, dict):
                    continue
                excerpt = highlight.get("highlighted_text")
                if not isinstance(excerpt, str) or not excerpt.strip():
                    continue
                locator: dict[str, JsonValue] = {"origin": "highlight"}
                page_number = highlight.get("page_number")
                if isinstance(page_number, int):
                    locator["page_number"] = page_number
                direct_sources.append(
                    DocumentSourceCandidate(
                        document_id=document_id,
                        excerpt=excerpt,
                        title=title if isinstance(title, str) else None,
                        locator=locator,
                    )
                )

        packet_context: dict[str, JsonValue] = {
            "conversation": _JSON_VALUE.validate_python(context_guidance),
            "resolved_citations": _JSON_VALUE.validate_python(artifact_payloads),
        }
        candidate_document_ids = {
            source.document_id
            for observation in tool_state.observations
            for source in observation.sources
            if isinstance(source, DocumentSourceCandidate)
        }
        candidate_document_ids.update(source.document_id for source in direct_sources)

        def verified_document_source_texts(
            capabilities: ApplicationCapabilities,
        ) -> dict[uuid.UUID, tuple[str, ...]]:
            verified: dict[uuid.UUID, tuple[str, ...]] = {}
            for document_id in candidate_document_ids:
                try:
                    paper = capabilities.paper_content.read(
                        actor=current_user,
                        document_id=document_id,
                    )
                except AppError:
                    continue
                verified[document_id] = tuple(
                    text
                    for text in (paper.raw_content, paper.abstract)
                    if text is not None and text.strip()
                )
            return verified

        source_texts = executor.query(verified_document_source_texts)
        for source in direct_sources:
            if (
                source.locator is not None
                and source.locator.get("origin") == "highlight"
                and source.document_id in source_texts
            ):
                source_texts[source.document_id] = (
                    *source_texts[source.document_id],
                    source.excerpt,
                )
        answer_packet = AnswerPacketBuilder().build(
            context=packet_context,
            tool_state=tool_state,
            direct_sources=direct_sources,
            user_materials=user_references or (),
            document_source_texts=source_texts,
        )
        grounded_parser = GroundedAnswerStreamParser(answer_packet.sources)
        formatted_system_prompt = CONVERSATION_ANSWER_SYSTEM_PROMPT.format(
            available_papers=formatted_paper_options,
        )
        formatted_system_prompt += final_answer_role_instructions(scope_type)
        formatted_system_prompt += (
            "\n\n## Required Citation Control Protocol\n" + grounded_parser.instructions
        )
        message_content: list[TextContent | SupplementaryContent] = [
            SupplementaryContent(
                content=answer_packet.model_dump_json(),
                label="answer_packet",
            ),
            TextContent(text=formatted_prompt),
        ]

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
            try:
                blocking_iterator = self.send_message_stream(
                    message=message_content,
                    system_prompt=formatted_system_prompt,
                    history=conversation_history,
                    reasoning_level=reasoning_level,
                )
                async for chunk in iterate_in_thread(blocking_iterator):
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

                logger.debug(
                    "llm.stream.chunk_received", extra={"chunk_chars": len(text)}
                )

                if not text:
                    continue

                filtered = grounded_parser.feed(text)
                if filtered:
                    yield {"type": "content", "content": filtered}
        finally:
            if not pinger_task.done():
                pinger_task.cancel()
            if not stream_reader_task.done():
                stream_reader_task.cancel()

        try:
            await stream_reader_task
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            raise classify_llm_error(exc, stage="final_answer") from exc

        remaining = grounded_parser.finish()
        if remaining:
            yield {"type": "content", "content": remaining}
        references = grounded_parser.references()
        citation_metrics = grounded_parser.metrics()
        tool_state.citation_metrics = {
            "source_candidates_input": sum(
                len(observation.sources) for observation in tool_state.observations
            )
            + len(direct_sources),
            "sources_registered": len(answer_packet.sources),
            "sources_rejected": answer_packet.coverage.rejected_sources,
            "document_sources": sum(
                source.kind == "document" for source in answer_packet.sources
            ),
            "external_sources": sum(
                source.kind == "external" for source in answer_packet.sources
            ),
            "annotations_emitted": citation_metrics.annotations_emitted,
            "invalid_source_keys": citation_metrics.invalid_source_keys,
            "protocol_errors": citation_metrics.protocol_errors,
        }
        if references is not None:
            yield {
                "type": "references",
                "content": references.model_dump(mode="json"),
            }
