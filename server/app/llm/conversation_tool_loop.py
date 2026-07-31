import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.telemetry import track_event
from app.llm.base import BaseLLMClient
from app.llm.conversation_prompts import scope_system_instructions
from app.llm.prompts import (
    EVIDENCE_COMPACTION_PROMPT,
    KEYWORD_EXTRACTION_PROMPT,
    TOOL_LOOP_MESSAGE,
    TOOL_LOOP_SYSTEM_PROMPT,
    TOOL_RESULT_COMPACTION_PROMPT,
)
from app.llm.backend import SupplementaryContent, TextContent
from app.modules.papers.application.contracts.citation import CitationResult
from app.modules.conversations.application.contracts.messages import (
    EvidenceSummaryResponse,
    OriginalSnippet,
    ToolRunState,
    ToolResultCompactionResponse,
)
from app.modules.integrations.connectors.infrastructure.mcp import (
    ConnectorToolResolver,
    ResolvedConnectorToolSet,
)
from app.shared.application import (
    Actor,
    ApplicationExecutor,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
)
from app.modules.conversations.application.chat import ConversationChatScope
from app.shared.domain import AppError
from app.tooling import (
    ToolAccess,
    ToolCatalog,
    ToolDispatcher,
    ToolExecutionContext,
    ToolOutcome,
)
from app.tooling.workspace import CONVERSATION_TOOL_PROFILE

logger = logging.getLogger(__name__)

# Conservative backend-independent limits leave room for system prompts,
# history, and responses while keeping cost and latency bounded.
# At ~4 chars/token: 150k chars ≈ 37.5k tokens, 400k chars ≈ 100k tokens
CONTENT_LIMIT_TOOL_RESULTS = 150000
CONTENT_LIMIT_CHAT_EVIDENCE = (
    300000  # Character limit for evidence in chat response prompt
)
HEARTBEAT_INTERVAL_SECONDS = (
    15  # Keep streaming connections alive during long operations
)

# Structured-output schema for the fallback keyword extractor — provider
# constrains the response to this shape so we never have to scrape JSON out of
# a markdown fence again.
KEYWORD_EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["keywords"],
}


def _summarize_citation(result: CitationResult) -> str:
    """A compact, text summary of a citation result for the answer model.

    The full structured data is delivered to the user separately, so the answer
    model should not re-paste a formatted citation.
    """
    d = result.data
    return (
        f"Resolved citation metadata for paper {result.document_id} "
        f"(preferred style: {result.style_display}; method: {result.method}). "
        f"Title: {d.title}; Journal: {d.journal}; Publisher: {d.publisher}; "
        f"DOI: {d.doi}; Date: {d.publish_date}. "
        f"Still missing: {result.missing_fields or 'none'}. "
        "This citation is delivered to the user separately; do not write out a "
        "formatted citation string in your answer."
    )


class ConversationToolLoop(BaseLLMClient):
    """Shared model-tool loop for every Conversation entry point."""

    def __init__(
        self,
        *,
        catalog: ToolCatalog[ApplicationCapabilities],
        dispatcher: ToolDispatcher[ApplicationCapabilities],
        connector_tools: ConnectorToolResolver,
        operation_factory: OperationContextFactory,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._dispatcher = dispatcher
        self._connector_tools = connector_tools
        self._operation_factory = operation_factory

    async def run_tools(
        self,
        question: str,
        current_user: Actor,
        executor: ApplicationExecutor[ApplicationCapabilities],
        conversation_scope: ConversationChatScope,
        conversation_id: uuid.UUID,
        turn_id: uuid.UUID,
        client_ip: str,
        request_operation: OperationContext,
        turn_correlation_id: uuid.UUID,
        user_operation_id: uuid.UUID,
    ) -> AsyncGenerator[dict[str, object], None]:
        """Use the shared catalog to gather evidence or perform requested actions."""
        conversation_history = executor.query(
            lambda capabilities: capabilities.conversation_chat_data.history(
                actor=current_user,
                conversation_id=conversation_id,
                exclude_turn_id=turn_id,
            )
        )

        tool_state = ToolRunState()

        n_iterations = 0
        max_iterations = 4

        context_snapshot = executor.query(
            lambda capabilities: capabilities.conversation_chat_data.context(
                actor=current_user,
                scope=conversation_scope,
            )
        )

        formatted_paper_options = {
            str(paper.document_id): {
                "title": paper.title,
                "length": len(paper.raw_content) if paper.raw_content else None,
                "keywords": paper.keywords or [],
                "authors": paper.authors,
                "published": paper.publish_date,
            }
            for paper in context_snapshot.papers
        }
        formatted_context = {
            "papers": formatted_paper_options,
            "projects": {
                str(project.project_id): {
                    "title": project.title,
                    "description": project.description,
                    "document_count": project.document_count,
                }
                for project in context_snapshot.projects
            },
            "available_document_count": context_snapshot.available_document_count,
        }

        tool_access = ToolAccess(
            profile_name=CONVERSATION_TOOL_PROFILE,
            permissions=conversation_scope.tool_permissions,
        )
        tool_declarations = self._catalog.provider_declarations(tool_access)
        connector_tool_set = await self._connector_tools.resolve(
            actor=current_user,
            permissions=conversation_scope.tool_permissions,
            reserved_names={
                str(declaration["name"]) for declaration in tool_declarations
            },
        )
        tool_declarations.extend(connector_tool_set.declarations)
        for issue in connector_tool_set.issues:
            yield {
                "type": "status",
                "content": issue.message,
            }

        prev_queries = set()
        should_stop = False

        while n_iterations < max_iterations and not should_stop:
            n_iterations += 1

            # If tool call results are very large, compact them to avoid context overflow
            tool_results_size = tool_state.get_tool_results_size()

            if tool_results_size > CONTENT_LIMIT_TOOL_RESULTS:
                yield {
                    "type": "status",
                    "content": "Gathered a lot of data. Compacting tool results...",
                }
                logger.info(
                    f"Tool results size exceeded {CONTENT_LIMIT_TOOL_RESULTS} "
                    f"characters ({tool_results_size}), compacting."
                )
                await self.compact_tool_call_results(
                    tool_state,
                    question,
                    current_user,
                )

            tool_loop_prompt = TOOL_LOOP_SYSTEM_PROMPT.format(
                available_papers=formatted_context,
                n_iteration=n_iterations,
                max_iterations=max_iterations,
            ) + scope_system_instructions(conversation_scope.scope_type)

            formatted_prompt = TOOL_LOOP_MESSAGE.format(
                question=question,
            )

            message_content: list[TextContent | SupplementaryContent] = [
                TextContent(text=formatted_prompt),
            ]
            anchor_paper = next(
                (
                    paper
                    for paper in context_snapshot.papers
                    if paper.document_id == conversation_scope.document_id
                ),
                None,
            )
            if anchor_paper is not None and anchor_paper.raw_content:
                message_content.insert(
                    0,
                    SupplementaryContent(
                        label="anchor_paper_full_text",
                        content=anchor_paper.raw_content,
                    ),
                )

            yield {
                "type": "status",
                "content": f"Reviewing collected evidence (iteration {n_iterations}/{max_iterations})...",
            }

            # Get tool call results from previous iterations
            tool_call_results = (
                tool_state.get_tool_call_results()
                if tool_state.has_tool_calls()
                else None
            )

            llm_response = self.generate_content(
                system_prompt=tool_loop_prompt,
                history=conversation_history,
                contents=message_content,
                function_declarations=tool_declarations,
                tool_call_results=tool_call_results,
            )

            if len(llm_response.tool_calls) == 0:
                logger.info("No tool calls returned from LLM, ending tool loop.")
                break

            dispatches = []
            for tool_call in llm_response.tool_calls:
                start_time = time.time()
                tool_name = tool_call.name.lower()
                tool_arguments = tool_call.args
                call_signature = json.dumps(
                    {
                        "name": tool_name,
                        "arguments": tool_arguments,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                if call_signature in prev_queries:
                    logger.info(
                        "Skipping repeated tool call",
                        extra={"tool_name": tool_name},
                    )
                    continue
                prev_queries.add(call_signature)
                tool_state.add_tool_call(tool_call)
                document_id_arg = tool_arguments.get("document_id")
                query_arg = tool_arguments.get("query")
                paper_name = (
                    formatted_paper_options.get(str(document_id_arg), {}).get(
                        "title",
                        "workspace",
                    )
                    if document_id_arg
                    else "workspace"
                )
                display_query = f" '{query_arg}'" if query_arg else ""
                display_name = tool_name.replace("_", " ").title()
                status = f"{display_name} - {paper_name}{display_query}"
                yield {"type": "status", "content": status}
                logger.debug("Tool-loop reasoning: %s", llm_response.thinking)

                dispatch_task = asyncio.create_task(
                    self._dispatch_tool(
                        name=tool_name,
                        arguments=tool_arguments,
                        connector_tool_set=connector_tool_set,
                        context=ToolExecutionContext(
                            actor=current_user,
                            operation=self._operation_factory.resume(
                                correlation_id=turn_correlation_id,
                                causation_id=user_operation_id,
                                initiated_by=OperationInitiator.AGENT,
                                origin=request_operation.origin,
                                credential=request_operation.credential,
                            ),
                            paper_collection=conversation_scope.paper_context,
                            anchor_document_id=conversation_scope.document_id,
                            invocation_id=(
                                f"conversation:{conversation_id}:{turn_id}:"
                                f"{hashlib.sha256(call_signature.encode()).hexdigest()}"
                            ),
                            client_ip=client_ip,
                        ),
                        access=tool_access,
                    )
                )
                dispatches.append(
                    (tool_call, tool_name, status, start_time, dispatch_task)
                )

            for tool_call, tool_name, status, start_time, dispatch_task in dispatches:
                connector_provider = connector_tool_set.provider_for(tool_name)
                result_status = "success"
                try:
                    while True:
                        try:
                            outcome = await asyncio.wait_for(
                                asyncio.shield(dispatch_task),
                                timeout=HEARTBEAT_INTERVAL_SECONDS,
                            )
                            break
                        except asyncio.TimeoutError:
                            yield {"type": "status", "content": status}

                    tool_result = outcome.payload
                    for artifact_payload in outcome.artifacts:
                        artifact = CitationResult.model_validate(artifact_payload)
                        tool_state.add_artifact(artifact)
                        tool_result = _summarize_citation(artifact)
                    for document_id, lines in outcome.evidence.items():
                        tool_state.add_evidence(
                            document_id,
                            lines,
                            preserve_line_numbers=True,
                        )
                    if outcome.action is not None:
                        tool_state.add_action_result(outcome.action)
                    tool_state.add_tool_call_result(tool_call, tool_result)
                    if outcome.stop:
                        should_stop = True
                except AppError as exc:
                    result_status = exc.code
                    logger.info(
                        "Tool call rejected",
                        extra={"tool_name": tool_name, "error_code": exc.code},
                    )
                    tool_state.add_tool_call_result(
                        tool_call,
                        {
                            "error": {
                                "code": exc.code,
                                "message": exc.message,
                                "details": exc.details,
                            }
                        },
                    )
                    yield {"type": "error", "content": exc.code}
                except Exception:
                    result_status = "tool_execution_failed"
                    logger.exception(
                        "Conversation tool execution failed",
                        extra={"tool_name": tool_name},
                    )
                    tool_state.add_tool_call_result(
                        tool_call,
                        {"error": {"code": "tool_execution_failed"}},
                    )
                    yield {"type": "error", "content": "tool_execution_failed"}

                track_event(
                    "tool_call",
                    {
                        "tool_name": tool_name,
                        "provider": (
                            connector_provider.value
                            if connector_provider is not None
                            else "local"
                        ),
                        "result_status": result_status,
                        "duration_ms": (time.time() - start_time) * 1000,
                        "conversation_scope_type": conversation_scope.scope_type.value,
                    },
                    user_id=str(current_user.id),
                )

        # A successful action or artifact is already a complete tool-loop
        # outcome. Only pure unanswered questions receive a keyword fallback.
        if (
            not tool_state.has_evidence()
            and not tool_state.get_artifacts()
            and not tool_state.action_results
            and not tool_state.has_informational_results()
            and self._catalog.is_available(tool_access, "search_papers")
        ):
            logger.info(
                "No evidence gathered through normal flow. "
                "Attempting fallback keyword search."
            )
            yield {
                "type": "status",
                "content": "Searching for relevant information...",
            }

            try:
                keywords = await self._extract_search_keywords(question)

                if keywords:
                    logger.info(f"Fallback search with keywords: {keywords}")

                    for keyword in keywords:
                        outcome = await self._dispatcher.dispatch(
                            name="search_papers",
                            raw_arguments={"query": keyword},
                            context=ToolExecutionContext(
                                actor=current_user,
                                operation=self._operation_factory.resume(
                                    correlation_id=turn_correlation_id,
                                    causation_id=user_operation_id,
                                    initiated_by=OperationInitiator.AGENT,
                                    origin=request_operation.origin,
                                    credential=request_operation.credential,
                                ),
                                paper_collection=conversation_scope.paper_context,
                                anchor_document_id=conversation_scope.document_id,
                                invocation_id=(
                                    f"conversation:{conversation_id}:{turn_id}:fallback"
                                ),
                                client_ip=client_ip,
                            ),
                            access=tool_access,
                        )
                        for document_id, lines in outcome.evidence.items():
                            tool_state.add_evidence(
                                document_id,
                                lines,
                                preserve_line_numbers=True,
                            )

                    if tool_state.has_evidence():
                        logger.info(
                            f"Fallback search found evidence from "
                            f"{len(tool_state.evidence)} papers"
                        )
                        track_event(
                            "fallback_search_success",
                            {
                                "keywords": keywords,
                                "papers_found": len(tool_state.evidence),
                            },
                            user_id=str(current_user.id),
                        )
                    else:
                        logger.info("Fallback search found no relevant evidence")
                        track_event(
                            "fallback_search_no_results",
                            {"keywords": keywords},
                            user_id=str(current_user.id),
                        )
            except Exception as e:
                logger.exception("Fallback search failed")
                track_event(
                    "fallback_search_error",
                    {"error_type": type(e).__name__},
                    user_id=str(current_user.id),
                )

        # Compact evidence if it exceeds the limit for chat response
        evidence_size = tool_state.get_evidence_size()
        if evidence_size > CONTENT_LIMIT_CHAT_EVIDENCE:
            yield {
                "type": "status",
                "content": "Compacting gathered evidence...",
            }
            logger.info(
                f"Evidence size ({evidence_size} chars) exceeds limit "
                f"({CONTENT_LIMIT_CHAT_EVIDENCE} chars). Compacting."
            )
            async for compaction_status in self.compact_evidence(
                tool_state,
                question,
                current_user,
            ):
                yield compaction_status

        yield {
            "type": "tool_run_completed",
            "content": tool_state,
        }

    async def _dispatch_tool(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        connector_tool_set: ResolvedConnectorToolSet,
        context: ToolExecutionContext,
        access: ToolAccess,
    ) -> ToolOutcome:
        if connector_tool_set.has_tool(name):
            return ToolOutcome(
                payload=await connector_tool_set.call(name, arguments)
            )
        return await self._dispatcher.dispatch(
            name=name,
            raw_arguments=arguments,
            context=context,
            access=access,
        )

    async def compact_tool_call_results(
        self,
        tool_state: ToolRunState,
        original_question: str,
        current_user: Actor,
    ) -> None:
        """
        Compact tool call results by summarizing them to reduce context size.
        Modifies the tool run state in place.
        """
        start_time = time.time()
        original_size = tool_state.get_tool_results_size()
        original_count = len(tool_state.tool_call_results)

        tool_results_for_compaction = tool_state.get_tool_results_for_compaction()

        formatted_prompt = TOOL_RESULT_COMPACTION_PROMPT.format(
            question=original_question,
            tool_results=json.dumps(tool_results_for_compaction, indent=2),
            schema=ToolResultCompactionResponse.model_json_schema(),
        )

        message_content = [TextContent(text=formatted_prompt)]

        llm_response = self.generate_content(
            system_prompt="You are a research assistant that summarizes tool call results while preserving key information.",
            contents=message_content,
            response_model=ToolResultCompactionResponse,
        )

        try:
            if llm_response and llm_response.text:
                compaction_response = ToolResultCompactionResponse.model_validate_json(
                    llm_response.text
                )

                tool_state.apply_compacted_results(
                    compaction_response.compacted_results
                )

                new_size = tool_state.get_tool_results_size()
                logger.info(
                    f"Tool result compaction complete. "
                    f"Original: {original_count} results ({original_size} chars), "
                    f"Compacted: {len(compaction_response.compacted_results)} results ({new_size} chars)"
                )

                track_event(
                    "tool_results_compacted",
                    {
                        "duration_ms": (time.time() - start_time) * 1000,
                        "original_count": original_count,
                        "original_size": original_size,
                        "compacted_count": len(compaction_response.compacted_results),
                        "compacted_size": new_size,
                    },
                    user_id=str(current_user.id),
                )
            else:
                logger.warning("Empty response from LLM during tool result compaction.")

        except Exception as e:
            logger.warning(
                f"Tool result compaction failed: {e}. Keeping original results."
            )

    async def compact_evidence(
        self,
        tool_state: ToolRunState,
        original_question: str,
        current_user: Actor,
    ) -> AsyncGenerator[dict[str, object], None]:
        """
        Compact evidence to reduce context size for chat response.
        Modifies the tool run state in place.

        Single-pass compaction: summarizes all evidence per paper in one LLM call.
        """
        start_time = time.time()
        original_size = tool_state.get_evidence_size()
        evidence_dict = tool_state.get_evidence_dict()
        original_count = sum(len(snippets) for snippets in evidence_dict.values())

        yield {
            "type": "status",
            "content": "Compacting evidence...",
        }

        # Format evidence for compaction with strict size limits
        # Sort papers by snippet count (most evidence first) and limit total size

        MAX_TOTAL_CHARS = 80000  # Total input limit for fast compaction
        MAX_PER_PAPER = 5000  # Per-paper limit
        MAX_SNIPPET_CHARS = 2000  # Per-snippet limit for indexed format

        papers_by_evidence = sorted(
            evidence_dict.items(), key=lambda x: len(x[1]), reverse=True
        )

        # Store original snippets in citation_index sidecar BEFORE compaction
        for document_id, snippets in papers_by_evidence:
            evidence_obj = tool_state.evidence.get(document_id)
            line_numbers = evidence_obj.get_line_numbers() if evidence_obj else []

            for i, snippet in enumerate(snippets):
                key = f"{document_id}:{i}"
                tool_state.citation_index.index[key] = OriginalSnippet(
                    document_id=document_id,
                    text=snippet,  # Full original text preserved
                    line_number=line_numbers[i] if i < len(line_numbers) else None,
                )

        # Format evidence with indexed snippets for LLM
        evidence_for_compaction: list[dict[str, Any]] = []
        total_chars = 0
        for document_id, snippets in papers_by_evidence:
            # Build indexed snippets for this paper
            indexed_snippets = []
            paper_chars = 0
            for i, snippet in enumerate(snippets):
                truncated = snippet[:MAX_SNIPPET_CHARS]
                if paper_chars + len(truncated) > MAX_PER_PAPER:
                    break
                indexed_snippets.append({"index": i, "text": truncated})
                paper_chars += len(truncated)

            if total_chars + paper_chars > MAX_TOTAL_CHARS:
                break

            evidence_for_compaction.append(
                {
                    "document_id": document_id,
                    "snippets": indexed_snippets,
                }
            )
            total_chars += paper_chars

        logger.info(
            f"Compacting {len(evidence_for_compaction)}/{len(evidence_dict)} papers ({total_chars} chars)"
        )

        formatted_prompt = EVIDENCE_COMPACTION_PROMPT.format(
            question=original_question,
            evidence=json.dumps(evidence_for_compaction, indent=2),
            schema=EvidenceSummaryResponse.model_json_schema(),
        )

        message_content = [TextContent(text=formatted_prompt)]

        llm_response = self.generate_content(
            system_prompt="You are a research assistant that summarizes evidence snippets from research papers.",
            contents=message_content,
            response_model=EvidenceSummaryResponse,
        )

        all_compacted: dict[str, list[str]] = {}

        try:
            if llm_response and llm_response.text:
                compaction_response = EvidenceSummaryResponse.model_validate_json(
                    llm_response.text
                )

                for paper_summary in compaction_response.papers:
                    if paper_summary.summary:
                        all_compacted[paper_summary.document_id] = [
                            paper_summary.summary
                        ]
            else:
                logger.warning("Empty response from LLM during evidence compaction.")

            # Add truncated fallback for papers not sent to LLM (due to size limits)
            for document_id, snippets in evidence_dict.items():
                if document_id not in all_compacted:
                    all_compacted[document_id] = [
                        f"(summarized) {' '.join(snippets)[:500]}..."
                    ]
        except Exception as e:
            logger.warning(
                f"Evidence compaction failed: {e}. Using truncated fallback."
            )
            for document_id, snippets in evidence_dict.items():
                all_compacted[document_id] = [
                    f"(summarized) {' '.join(snippets)[:500]}..."
                ]

        tool_state.apply_compacted_evidence(all_compacted)
        tool_state.is_compacted = True

        new_size = tool_state.get_evidence_size()
        new_count = sum(len(snippets) for snippets in all_compacted.values())

        logger.info(
            f"Evidence compaction complete. "
            f"Original: {original_count} snippets ({original_size} chars), "
            f"Compacted: {new_count} summaries ({new_size} chars)"
        )

        track_event(
            "evidence_compacted",
            {
                "duration_ms": (time.time() - start_time) * 1000,
                "original_count": original_count,
                "original_size": original_size,
                "compacted_count": new_count,
                "compacted_size": new_size,
            },
            user_id=str(current_user.id),
        )

    async def _extract_search_keywords(
        self,
        question: str,
    ) -> list[str]:
        """Extract search keywords from a question using LLM."""
        formatted_prompt = KEYWORD_EXTRACTION_PROMPT.format(question=question)

        message_content = [TextContent(text=formatted_prompt)]

        llm_response = self.generate_content(
            system_prompt=(
                "You extract search keywords. Respond only with the JSON object "
                "matching the schema."
            ),
            contents=message_content,
            schema=KEYWORD_EXTRACTION_SCHEMA,
        )

        if llm_response and llm_response.text:
            try:
                parsed = json.loads(llm_response.text)
                keywords = (
                    parsed.get("keywords", []) if isinstance(parsed, dict) else []
                )
                return [str(k) for k in keywords if k][:5]
            except (json.JSONDecodeError, AttributeError):
                logger.warning(
                    f"Failed to parse keyword schema response: {llm_response.text}"
                )

        logger.warning("Failed to extract keywords from question")
        return []
