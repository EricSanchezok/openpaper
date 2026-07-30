"""External, persistence-free recovery of missing paper metadata."""

import json
import logging
from typing import Any

from app.modules.papers.domain.citations import CitationFields
from app.modules.conversations.infrastructure.mcp_client import (
    call_remote_tool_sync,
    discover_function_declarations_sync,
)
from app.llm.base import BaseLLMClient
from app.modules.papers.application.contracts.citation import CitationStep
from app.modules.papers.application.contracts.extraction import (
    TextContent,
    ToolCallResult,
)

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7
MAX_WEB_ITERATIONS = 3

# JSON schema for the forced extraction backstop. Every field is required and
# nullable so the model must return a complete, honest result shape.
CITATION_EXTRACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "journal": {"type": ["string", "null"]},
        "publisher": {"type": ["string", "null"]},
        "doi": {"type": ["string", "null"]},
        "publish_date": {"type": ["string", "null"]},
        "source_url": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
    },
    "required": [
        "journal",
        "publisher",
        "doi",
        "publish_date",
        "source_url",
        "confidence",
    ],
}

RECOVERY_SYSTEM_PROMPT = (
    "You are a bibliographic research assistant. Your job is to find the "
    "missing publication metadata (journal/venue, publisher, DOI, publication "
    "date) for one specific academic paper so it can be cited correctly.\n\n"
    "Use search for broad web results, search_papers for Scholight's ranked "
    "academic index, and extract only when a search result is not enough. "
    "Critically verify that a source describes THE SAME paper by matching its "
    "title and authors.\n\n"
    "Be decisive and efficient — you usually need only ONE or TWO searches. As "
    "soon as a result reveals the venue/publisher/DOI, stop searching and call "
    "submit_findings; do not keep searching for perfection. You have a strict, "
    "small number of steps. Always finish by calling submit_findings exactly "
    "once: include the fields you are confident about with an honest confidence "
    "score, or a low confidence score if you could not determine them."
)

submit_findings_function = {
    "name": "submit_findings",
    "description": (
        "Report the bibliographic fields you found for this paper. Provide only "
        "fields you are confident about; omit unknown ones. Call this exactly "
        "once when you are done."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "journal": {
                "type": "string",
                "description": "The journal or publication venue name.",
            },
            "publisher": {"type": "string", "description": "The publisher name."},
            "doi": {
                "type": "string",
                "description": "The DOI identifier (no URL prefix).",
            },
            "publish_date": {
                "type": "string",
                "description": "Publication date as YYYY-MM-DD or YYYY.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence from 0.0 to 1.0 that these values are correct for THIS paper.",
            },
            "source_url": {
                "type": "string",
                "description": "The URL these values were taken from.",
            },
        },
        "required": ["confidence"],
    },
}


class MetadataRecoveryAgent(BaseLLMClient):
    """Web-search + extraction agent that returns provider facts only."""

    def find_metadata(
        self,
        *,
        fields: CitationFields,
        missing_fields: list[str],
        steps: list[CitationStep],
    ) -> tuple[dict[str, Any], float | None]:
        """Resolve metadata through external providers without database access."""
        if not missing_fields:
            return {}, None
        findings = self._run_web_loop(fields, missing_fields, steps)
        if not findings:
            return {}, None
        confidence = float(findings.get("confidence") or 0.0)
        if confidence < CONFIDENCE_THRESHOLD:
            steps.append(
                CitationStep(
                    kind="write_back",
                    detail=(
                        "Findings below confidence threshold "
                        f"({confidence}); not written back."
                    ),
                    data=findings,
                )
            )
            return {}, confidence
        return findings, confidence

    def _describe_task(self, fields: CitationFields, missing: list[str]) -> str:
        authors = ", ".join(fields.authors) if fields.authors else "unknown"
        return (
            "Find the missing publication metadata for this paper.\n\n"
            f"- Title: {fields.title or 'unknown'}\n"
            f"- Authors: {authors}\n"
            f"- DOI: {fields.doi or 'unknown'}\n"
            f"- Publication date: {fields.publish_date or 'unknown'}\n"
            f"- Journal/venue: {fields.journal or 'unknown'}\n"
            f"- Publisher: {fields.publisher or 'unknown'}\n\n"
            f"Specifically needed: {', '.join(missing)}.\n"
            "Search for the paper, verify the source matches its title and "
            "authors, then call submit_findings."
        )

    def _run_web_loop(
        self,
        fields: CitationFields,
        missing: list[str],
        steps: list[CitationStep],
    ) -> dict[str, Any] | None:
        try:
            remote_declarations = [
                declaration
                for declaration in discover_function_declarations_sync()
                if declaration["name"] in {"search", "extract", "search_papers"}
            ]
        except Exception:
            logger.exception("Failed to discover citation MCP tools")
            remote_declarations = []
        function_declarations = [*remote_declarations, submit_findings_function]
        remote_tool_names = {
            str(declaration["name"]) for declaration in remote_declarations
        }
        user_msg = self._describe_task(fields, missing)
        tool_call_results: list[ToolCallResult] = []
        prev_queries: set[str] = set()

        for _ in range(MAX_WEB_ITERATIONS):
            try:
                resp = self.generate_content(
                    system_prompt=RECOVERY_SYSTEM_PROMPT,
                    contents=[TextContent(text=user_msg)],
                    function_declarations=function_declarations,
                    tool_call_results=tool_call_results or None,
                )
            except Exception:
                logger.exception("Citation web loop LLM call failed")
                break

            if resp.thinking:
                steps.append(CitationStep(kind="thinking", detail=resp.thinking[:500]))

            if not resp.tool_calls:
                break

            submitted: dict[str, Any] | None = None
            for call in resp.tool_calls:
                name = (call.name or "").lower()
                args = call.args or {}

                if name == "submit_findings":
                    submitted = args
                    steps.append(
                        CitationStep(
                            kind="submit",
                            detail="Agent submitted findings.",
                            data=args,
                        )
                    )
                    continue

                if name not in remote_tool_names:
                    continue

                # Canonicalize args so semantically identical calls dedup
                # regardless of key ordering or whitespace from the model.
                try:
                    args_key = json.dumps(args, sort_keys=True, default=str)
                except (TypeError, ValueError):
                    args_key = str(args)
                dedup_key = f"{name}:{args_key}"
                if dedup_key in prev_queries:
                    continue
                prev_queries.add(dedup_key)

                try:
                    result = call_remote_tool_sync(name, args)
                except Exception as e:
                    logger.warning("Citation tool %s failed: %s", name, e)
                    result = f"Error: {e}"

                if name in {"search", "search_papers"}:
                    steps.append(
                        CitationStep(
                            kind="web_search",
                            detail=f"Searched: {args.get('query', '')}",
                            data={
                                "results": result if isinstance(result, list) else None
                            },
                        )
                    )
                elif name == "extract":
                    steps.append(
                        CitationStep(
                            kind="web_fetch",
                            detail=f"Fetched: {args.get('url', '')}",
                        )
                    )

                tool_call_results.append(
                    ToolCallResult(id=call.id, name=call.name, args=args, result=result)
                )

            if submitted is not None:
                return submitted

        # The model rarely calls submit_findings on its own, so back-stop with a
        # forced structured extraction over everything gathered.
        return self._extract_findings(fields, missing, tool_call_results, steps)

    def _extract_findings(
        self,
        fields: CitationFields,
        missing: list[str],
        tool_call_results: list[ToolCallResult],
        steps: list[CitationStep],
    ) -> dict[str, Any] | None:
        """Forced structured extraction of citation fields from gathered sources."""
        if not tool_call_results:
            return None

        context_chunks = []
        for r in tool_call_results:
            value = r.result
            if not isinstance(value, str):
                value = json.dumps(value, default=str)
            context_chunks.append(f"[{r.name} {r.args}]\n{value[:1500]}")
        context = "\n\n".join(context_chunks)[:6000]

        authors = ", ".join(fields.authors) if fields.authors else "unknown"
        prompt = (
            "Extract bibliographic metadata for this paper from the research "
            "notes below. Only return values you are confident belong to THIS "
            "exact paper (match the title and authors); use null otherwise. "
            "Give an honest overall confidence from 0.0 to 1.0.\n\n"
            f"Title: {fields.title or 'unknown'}\n"
            f"Authors: {authors}\n"
            f"Fields needed: {', '.join(missing)}.\n\n"
            f"Research notes:\n{context}"
        )
        try:
            resp = self.generate_content(
                system_prompt=(
                    "You extract structured bibliographic metadata. Respond only "
                    "with the JSON object matching the schema."
                ),
                contents=[TextContent(text=prompt)],
                schema=CITATION_EXTRACTION_SCHEMA,
            )
            parsed_findings = json.loads(resp.text)
            if not isinstance(parsed_findings, dict):
                raise ValueError("Citation extraction did not return an object")
            findings: dict[str, Any] = parsed_findings
        except Exception:
            logger.exception("Citation extraction failed")
            return None

        # If nothing usable was found, return None rather than a low-signal dict.
        if not any(
            findings.get(f) for f in ("journal", "publisher", "doi", "publish_date")
        ):
            steps.append(
                CitationStep(
                    kind="submit",
                    detail="No matching metadata found in gathered sources.",
                )
            )
            return None

        steps.append(
            CitationStep(
                kind="submit",
                detail="Extracted citation fields from gathered sources.",
                data=findings,
            )
        )
        return findings
