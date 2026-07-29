import asyncio
import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Mapping,
    cast,
)

from app.bootstrap.capabilities import ApplicationCapabilities
from app.database.telemetry import track_event
from app.llm.base import BaseLLMClient
from app.transport.agent.citation import find_citation_function, run_find_citation
from app.llm.prompts import (
    EVIDENCE_COMPACTION_PROMPT,
    EVIDENCE_GATHERING_MESSAGE,
    EVIDENCE_GATHERING_SYSTEM_PROMPT,
    KEYWORD_EXTRACTION_PROMPT,
    TOOL_RESULT_COMPACTION_PROMPT,
)
from app.llm.backend import TextContent
from app.transport.agent.paper_tools import (
    read_abstract,
    read_abstract_function,
    read_file,
    read_file_function,
    search_all_files,
    search_all_files_function,
    search_file,
    search_file_function,
    view_file,
    view_file_function,
)
from app.transport.agent.meta_tools import stop_function
from app.modules.papers.application.contracts.citation import CitationResult
from app.modules.conversations.application.contracts.messages import (
    EvidenceCollection,
    EvidenceSummaryResponse,
    OriginalSnippet,
    ToolResultCompactionResponse,
)
from app.shared.application import Actor, ApplicationExecutor

logger = logging.getLogger(__name__)

# Conservative backend-independent limits leave room for system prompts,
# history, and responses while keeping cost and latency bounded.
# At ~4 chars/token: 150k chars ≈ 37.5k tokens, 400k chars ≈ 100k tokens
CONTENT_LIMIT_EVIDENCE_GATHERING = (
    150000  # Character limit for tool results during evidence gathering
)
CONTENT_LIMIT_CHAT_EVIDENCE = (
    300000  # Character limit for evidence in chat response prompt
)
HEARTBEAT_INTERVAL_SECONDS = (
    15  # Keep streaming connections alive during long operations
)

_tool_executor = ThreadPoolExecutor(max_workers=4)

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


class EvidenceOperations(BaseLLMClient):
    """Operations related to evidence gathering and compaction from multiple papers."""

    async def gather_evidence(
        self,
        question: str,
        current_user: Actor,
        executor: ApplicationExecutor[ApplicationCapabilities],
        conversation_id: str | None = None,
        project_id: str | None = None,
        restrict_to_document_ids: list[str] | None = None,
    ) -> AsyncGenerator[
        Mapping[str, str | dict[str, list[str]] | EvidenceCollection], None
    ]:
        """
        Gather evidence from multiple papers based on the user's question.
        This function will interact with the LLM to gather relevant information
        and citations from the user's knowledge base.
        """
        conversation_history = (
            executor.query(
                lambda capabilities: capabilities.conversation_chat_data.history(
                    actor=current_user,
                    conversation_id=uuid.UUID(conversation_id),
                )
            )
            if conversation_id
            else []
        )

        # Initialize evidence collection
        evidence_collection = EvidenceCollection()

        n_iterations = 0
        max_iterations = 4

        all_papers = executor.query(
            lambda capabilities: capabilities.conversation_chat_data.papers(
                actor=current_user,
                project_id=uuid.UUID(project_id) if project_id else None,
            )
        )

        # @-mention scoping: hard-limit the available papers to the mentioned
        # set. Withholding out-of-scope papers from formatted_paper_options
        # means the model is never offered them, and the per-paper tools reject
        # any id that isn't listed here (see the guard in the tool-call loop).
        if restrict_to_document_ids is not None:
            allowed_ids = set(restrict_to_document_ids)
            all_papers = [
                paper for paper in all_papers if str(paper.document_id) in allowed_ids
            ]

        formatted_paper_options = {
            str(paper.document_id): {
                "title": paper.title,
                "length": len(str(paper.raw_content)),
                "keywords": paper.keywords or [],
                "authors": paper.authors,
                "published": paper.publish_date,
            }
            for paper in all_papers
        }

        function_declarations = [
            read_file_function,
            search_file_function,
            view_file_function,
            read_abstract_function,
            search_all_files_function,
            find_citation_function,
            stop_function,
        ]

        function_maps = {
            "read_file": read_file,
            "search_file": search_file,
            "view_file": view_file,
            "read_abstract": read_abstract,
            "search_all_files": search_all_files,
            "find_citation": run_find_citation,
            "stop": lambda: None,
        }

        prev_queries = set()
        should_stop = False

        while n_iterations < max_iterations and not should_stop:
            n_iterations += 1

            # If tool call results are very large, compact them to avoid context overflow
            tool_results_size = evidence_collection.get_tool_results_size()

            if tool_results_size > CONTENT_LIMIT_EVIDENCE_GATHERING:
                yield {
                    "type": "status",
                    "content": "Gathered a lot of data. Compacting tool results...",
                }
                logger.info(
                    f"Tool results size exceeded {CONTENT_LIMIT_EVIDENCE_GATHERING} "
                    f"characters ({tool_results_size}), compacting."
                )
                await self.compact_tool_call_results(
                    evidence_collection,
                    question,
                    current_user,
                )

            evidence_gathering_prompt = EVIDENCE_GATHERING_SYSTEM_PROMPT.format(
                available_papers=formatted_paper_options,
                n_iteration=n_iterations,
                max_iterations=max_iterations,
            )

            formatted_prompt = EVIDENCE_GATHERING_MESSAGE.format(
                question=question,
            )

            message_content = [
                TextContent(text=formatted_prompt),
            ]

            yield {
                "type": "status",
                "content": f"Reviewing collected evidence (iteration {n_iterations}/{max_iterations})...",
            }

            # Get tool call results from previous iterations
            tool_call_results = (
                evidence_collection.get_tool_call_results()
                if evidence_collection.has_previous_tool_calls()
                else None
            )

            llm_response = self.generate_content(
                system_prompt=evidence_gathering_prompt,
                history=conversation_history,
                contents=message_content,
                function_declarations=function_declarations,
                tool_call_results=tool_call_results,
            )

            if len(llm_response.tool_calls) == 0:
                logger.info(
                    "No tool calls returned from LLM, ending evidence gathering."
                )
                break

            for fn_selected in llm_response.tool_calls:
                start_time = time.time()

                fn_name_raw = fn_selected.name
                fn_name = fn_name_raw.lower() if fn_name_raw else fn_name_raw
                fn_args = fn_selected.args

                if fn_name == "stop":
                    logger.info(
                        "Received STOP signal from LLM. Will stop after processing "
                        "remaining tool calls in this batch."
                    )
                    should_stop = True
                    continue

                if f"{fn_name}:{fn_args}" in prev_queries:
                    logger.info(
                        f"Function call {fn_name} with args {fn_args} has already "
                        "been made, skipping to avoid repetition."
                    )
                    continue

                prev_queries.add(f"{fn_name}:{fn_args}")
                evidence_collection.add_tool_call(fn_selected)

                if fn_name in function_maps:
                    try:
                        document_id_arg = fn_args.get("document_id")
                        query_arg = fn_args.get("query")
                        paper_name = (
                            formatted_paper_options.get(str(document_id_arg), {}).get(
                                "title", "knowledge base"
                            )
                            if document_id_arg
                            else "knowledge base"
                        )

                        if (
                            document_id_arg
                            and document_id_arg not in formatted_paper_options
                        ):
                            logger.warning(
                                f"Paper ID {document_id_arg} not found in available papers."
                            )
                            evidence_collection.add_tool_call_result(
                                fn_selected,
                                f"Error: Paper ID {document_id_arg} not found",
                            )
                            continue

                        display_query = f" '{query_arg}'" if query_arg else ""
                        pretty_fn_name = fn_name.replace("_", " ").title()

                        yield {
                            "type": "status",
                            "content": f"{pretty_fn_name} - {paper_name}{display_query}",
                        }

                        logger.debug(f"Thinking process - {llm_response.thinking}")

                        # Run the tool call in a thread so we can yield
                        # heartbeats and keep the streaming connection alive.
                        selected_fn = cast(
                            Callable[..., object], function_maps[fn_name]
                        )
                        selected_args: Mapping[str, Any] = fn_args

                        def _run_tool() -> object:
                            return selected_fn(
                                **selected_args,
                                current_user=current_user,
                                project_id=project_id,
                                restrict_to_document_ids=restrict_to_document_ids,
                                executor=executor,
                            )

                        loop = asyncio.get_event_loop()
                        future = loop.run_in_executor(_tool_executor, _run_tool)

                        while True:
                            try:
                                result = await asyncio.wait_for(
                                    asyncio.shield(future),
                                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                                )
                                break
                            except asyncio.TimeoutError:
                                yield {
                                    "type": "status",
                                    "content": f"{pretty_fn_name} - {paper_name}{display_query}",
                                }

                        if fn_name == "find_citation" and isinstance(
                            result, CitationResult
                        ):
                            # Citations are first-party artifacts (rendered as a
                            # card client-side), not evidence. Capture the
                            # structured result and feed the model a short
                            # summary so it can reference but not re-paste it.
                            evidence_collection.add_artifact(result)
                            evidence_collection.add_tool_call_result(
                                fn_selected, _summarize_citation(result)
                            )
                        else:
                            tool_result = (
                                result
                                if isinstance(result, (str, list, dict))
                                or result is None
                                else str(result)
                            )
                            evidence_collection.add_tool_call_result(
                                fn_selected, tool_result
                            )

                            preserve_line_numbers = fn_name in [
                                "search_file",
                                "search_all_files",
                            ]

                            if fn_name == "search_all_files" and isinstance(
                                result, dict
                            ):
                                for document_id, lines in result.items():
                                    evidence_collection.add_evidence(
                                        document_id, lines, preserve_line_numbers=True
                                    )

                            document_id = fn_args.get("document_id")
                            if document_id and (
                                isinstance(result, str) or isinstance(result, list)
                            ):
                                evidence_collection.add_evidence(
                                    document_id,
                                    result,
                                    preserve_line_numbers=preserve_line_numbers,
                                )

                    except Exception:
                        logger.exception(
                            "Evidence tool execution failed",
                            extra={"tool_name": fn_name},
                        )
                        evidence_collection.add_tool_call_result(
                            fn_selected, "Error: tool_execution_failed"
                        )
                        yield {"type": "error", "content": "tool_execution_failed"}
                else:
                    logger.warning(f"Unknown function called: {fn_name_raw}")
                    yield {
                        "type": "error",
                        "content": f"Unknown function: {fn_name_raw}",
                    }

                end_time = time.time()
                track_event(
                    "function_call",
                    {
                        "function_name": fn_name,
                        "duration_ms": (end_time - start_time) * 1000,
                        "project_type": project_id is not None,
                    },
                    user_id=str(current_user.id),
                )

        # Fallback: if no evidence was gathered AND no artifacts (e.g. a pure
        # citation request that produced a card but no excerpt), try keyword-
        # based search. Artifacts count as a real outcome — don't waste a call.
        if (
            not evidence_collection.has_evidence()
            and not evidence_collection.get_artifacts()
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
                        search_results = search_all_files(
                            query=keyword,
                            current_user=current_user,
                            executor=executor,
                            project_id=project_id,
                            restrict_to_document_ids=restrict_to_document_ids,
                        )

                        if search_results:
                            for document_id, lines in search_results.items():
                                evidence_collection.add_evidence(
                                    document_id, lines, preserve_line_numbers=True
                                )

                    if evidence_collection.has_evidence():
                        logger.info(
                            f"Fallback search found evidence from "
                            f"{len(evidence_collection.evidence)} papers"
                        )
                        track_event(
                            "fallback_search_success",
                            {
                                "keywords": keywords,
                                "papers_found": len(evidence_collection.evidence),
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
        evidence_size = evidence_collection.get_evidence_size()
        if evidence_size > CONTENT_LIMIT_CHAT_EVIDENCE:
            yield {
                "type": "status",
                "content": "Compacting gathered evidence...",
            }
            logger.info(
                f"Evidence size ({evidence_size} chars) exceeds limit "
                f"({CONTENT_LIMIT_CHAT_EVIDENCE} chars). Compacting."
            )
            async for status in self.compact_evidence(
                evidence_collection,
                question,
                current_user,
            ):
                yield status

        yield {
            "type": "evidence_gathered",
            "content": evidence_collection,  # Full object preserves is_compacted and citation_index
        }

    async def compact_tool_call_results(
        self,
        evidence_collection: EvidenceCollection,
        original_question: str,
        current_user: Actor,
    ) -> None:
        """
        Compact tool call results by summarizing them to reduce context size.
        Modifies the evidence_collection in place.
        """
        start_time = time.time()
        original_size = evidence_collection.get_tool_results_size()
        original_count = len(evidence_collection.tool_call_results)

        tool_results_for_compaction = (
            evidence_collection.get_tool_results_for_compaction()
        )

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

                evidence_collection.apply_compacted_results(
                    compaction_response.compacted_results
                )

                new_size = evidence_collection.get_tool_results_size()
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
        evidence_collection: EvidenceCollection,
        original_question: str,
        current_user: Actor,
    ) -> AsyncGenerator[dict[str, str | dict[str, list[str]]], None]:
        """
        Compact evidence to reduce context size for chat response.
        Modifies the evidence_collection in place.

        Single-pass compaction: summarizes all evidence per paper in one LLM call.
        """
        start_time = time.time()
        original_size = evidence_collection.get_evidence_size()
        evidence_dict = evidence_collection.get_evidence_dict()
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
            evidence_obj = evidence_collection.evidence.get(document_id)
            line_numbers = evidence_obj.get_line_numbers() if evidence_obj else []

            for i, snippet in enumerate(snippets):
                key = f"{document_id}:{i}"
                evidence_collection.citation_index.index[key] = OriginalSnippet(
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

        evidence_collection.apply_compacted_evidence(all_compacted)
        evidence_collection.is_compacted = True

        new_size = evidence_collection.get_evidence_size()
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
