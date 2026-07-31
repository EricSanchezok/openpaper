import json
import re
import uuid
from typing import Any

from app.shared.application.context_budget import (
    estimate_tokens,
    truncate_to_token_budget,
)
from app.shared.domain.enums import ReasoningLevel
from app.modules.papers.application.contracts.citation import CitationResult
from app.modules.papers.application.contracts.extraction import ToolCall, ToolCallResult
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _serialize_tool_result(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return "None" if value is None else str(value)


def _tool_result_context(result: ToolCallResult) -> str:
    return json.dumps(result.model_dump(mode="json"), ensure_ascii=False, default=str)


class ConversationMessageRequest(BaseModel):
    """One stable message contract for every conversation scope."""

    model_config = ConfigDict(extra="forbid")

    turn_id: uuid.UUID
    user_query: str = Field(min_length=1, max_length=20_000)
    user_references: list[str] | None = Field(default=None, max_length=50)
    reasoning_level: ReasoningLevel = ReasoningLevel.STANDARD
    mentioned_highlight_ids: list[str] | None = Field(default=None, max_length=50)

    @field_validator("mentioned_highlight_ids")
    @classmethod
    def validate_mentioned_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None:
            for item in value:
                uuid.UUID(item)
        return value

    @field_validator("user_references")
    @classmethod
    def validate_references(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(len(item) > 5_000 for item in value):
            raise ValueError("Reference text exceeds maximum length")
        return value


class PaperEvidence(BaseModel):
    """Evidence collected from one paper during a tool run."""

    document_id: str = Field(
        ...,
        description="Unique identifier for the paper. Not to be used for user-facing responses. Only for internal tracking.",
    )
    content: list[str] = Field(
        default_factory=list, description="List of evidence content strings"
    )
    metadata: dict[str, list[str]] = Field(
        default_factory=dict, description="Metadata associated with the evidence"
    )

    def add_content(
        self, content: str | list[str], with_line_numbers: bool = False
    ) -> None:
        """Add content to the evidence"""
        if isinstance(content, str):
            self.content.append(content)
            if with_line_numbers:
                # Extract line numbers from content like "123: some text"
                line_match = re.match(r"^(\d+):\s*(.+)", content)
                if line_match:
                    line_num = line_match.group(1)
                    clean_content = line_match.group(2)
                    if "line_numbers" not in self.metadata:
                        self.metadata["line_numbers"] = []
                    self.metadata["line_numbers"].append(line_num)
                    # Replace with clean content
                    self.content[-1] = clean_content
        else:
            for item in content:
                self.add_content(item, with_line_numbers)

    def get_clean_content(self) -> list[str]:
        """Get content without line number prefixes"""
        return self.content

    def get_line_numbers(self) -> list[str]:
        """Get associated line numbers"""
        return self.metadata.get("line_numbers", [])


class OriginalSnippet(BaseModel):
    """An original evidence snippet with its source metadata."""

    document_id: str = Field(description="The paper ID this snippet came from")
    text: str = Field(description="The original snippet text")
    line_number: str | None = Field(
        default=None, description="Line number in source paper"
    )


class CitationIndex(BaseModel):
    """Maps compaction citation markers to original evidence snippets."""

    # Key: "{document_id}:{snippet_index}" e.g., "abc123:0"
    index: dict[str, OriginalSnippet] = Field(
        default_factory=dict,
        description="Mapping of document_id:index keys to original snippets",
    )


class ToolRunState(BaseModel):
    """Typed state produced by one Conversation tool loop."""

    evidence: dict[str, PaperEvidence] = Field(
        default_factory=dict, description="Mapping of paper IDs to their evidence"
    )
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="List of previous tool calls made during evidence gathering",
    )
    tool_call_results: list[ToolCallResult] = Field(
        default_factory=list,
        description="List of tool call results for proper multi-turn function calling",
    )
    informational_results: list[ToolCallResult] = Field(
        default_factory=list,
        description="Successful external research results available to the final answer.",
    )
    compacted_tool_result_indexes: set[int] = Field(
        default_factory=set,
        exclude=True,
        description="Internal indexes of raw tool results already summarized once.",
    )
    citation_index: CitationIndex = Field(
        default_factory=CitationIndex,
        description="Sidecar storage for original snippets during compaction",
    )
    is_compacted: bool = Field(
        default=False,
        description="Whether evidence has been compacted (citations need resolution)",
    )
    artifacts: list[CitationResult] = Field(
        default_factory=list,
        description="First-party artifacts produced during gathering (e.g. citations)",
    )
    action_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Successful state-changing tool outcomes.",
    )

    def add_action_result(self, result: dict[str, Any]) -> None:
        self.action_results.append(result)

    def add_artifact(self, artifact: CitationResult) -> None:
        """Record a first-party artifact (e.g. a resolved citation)."""
        self.artifacts.append(artifact)

    def get_artifacts(self) -> list[CitationResult]:
        return self.artifacts

    def to_trace_dict(self) -> dict[str, Any] | None:
        """Compact trajectory of this turn for user-facing inspection: the tool
        calls made and, for any citation subagent runs, their internal steps."""
        tool_calls = [{"name": tc.name, "args": tc.args} for tc in self.tool_calls]
        citations = [
            {
                "document_id": a.document_id,
                "method": a.method,
                "preferred_style": a.preferred_style,
                "steps": [step.model_dump() for step in a.steps],
            }
            for a in self.artifacts
        ]
        if not tool_calls and not citations:
            return {"actions": self.action_results} if self.action_results else None
        return {
            "tool_calls": tool_calls,
            "citations": citations,
            "actions": self.action_results,
        }

    def load_from_dict(self, evidence_dict: dict[str, list[str]]) -> None:
        """Load evidence from a dictionary format"""
        for document_id, content in evidence_dict.items():
            self.evidence[document_id] = PaperEvidence(
                document_id=document_id, content=content
            )

    def add_evidence(
        self,
        document_id: str,
        content: str | list[str],
        preserve_line_numbers: bool = False,
    ) -> None:
        """Add evidence for a specific paper"""
        if document_id not in self.evidence:
            self.evidence[document_id] = PaperEvidence(
                document_id=document_id,
                content=[],
            )
        self.evidence[document_id].add_content(
            content, with_line_numbers=preserve_line_numbers
        )

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the collection"""
        self.tool_calls.append(tool_call)

    def add_tool_call_result(
        self,
        tool_call: ToolCall,
        result: Any,
        *,
        informational: bool = False,
    ) -> None:
        """Add a tool call result for proper multi-turn function calling"""
        item = ToolCallResult(
            id=tool_call.id,
            name=tool_call.name,
            args=tool_call.args,
            result=result,
        )
        self.tool_call_results.append(item)
        if informational:
            self.informational_results.append(item)

    def get_tool_call_results(self) -> list[ToolCallResult]:
        """Get all tool call results for passing to LLM"""
        return self.tool_call_results

    def answer_tool_results(
        self, *, max_tokens: int | None = None
    ) -> list[dict[str, Any]]:
        """Successful informational results that the final answer may use.

        A final-answer budget keeps every result represented while bounding its
        payload. Tool-loop state itself remains unchanged.
        """
        if max_tokens is None or not self.informational_results:
            return [item.model_dump(mode="json") for item in self.informational_results]

        bounded: list[dict[str, Any]] = []
        remaining_tokens = max_tokens
        for offset, item in enumerate(self.informational_results):
            payload = item.model_dump(mode="json")
            original_result = payload.pop("result", None)
            serialized_result = _serialize_tool_result(original_result)
            remaining_items = len(self.informational_results) - offset
            metadata_tokens = estimate_tokens(
                json.dumps(payload, ensure_ascii=False, default=str)
            )
            result_budget = max(
                1,
                remaining_tokens // remaining_items - metadata_tokens,
            )
            bounded_result = truncate_to_token_budget(
                serialized_result,
                result_budget,
            )
            payload["result"] = (
                original_result
                if bounded_result == serialized_result
                else bounded_result
            )
            used_tokens = estimate_tokens(
                json.dumps(payload, ensure_ascii=False, default=str)
            )
            remaining_tokens = max(0, remaining_tokens - used_tokens)
            bounded.append(payload)
        return bounded

    def has_informational_results(self) -> bool:
        return bool(self.answer_tool_results())

    def get_evidence_dict(self) -> dict[str, list[str]]:
        """Return clean evidence content without line numbers."""
        return {
            document_id: evidence.get_clean_content()
            for document_id, evidence in self.evidence.items()
        }

    def get_evidence_dict_with_metadata(
        self,
    ) -> dict[str, dict[str, list[str] | dict[str, list[str]]]]:
        """Get evidence with metadata for agent context"""
        return {
            document_id: {"content": evidence.content, "metadata": evidence.metadata}
            for document_id, evidence in self.evidence.items()
        }

    def has_evidence(self) -> bool:
        """Check if any evidence has been collected"""
        return bool(self.evidence)

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def get_tool_results_size(self) -> int:
        """Calculate the total character size of all tool call results"""
        return sum(
            len(_serialize_tool_result(result.result))
            for result in self.tool_call_results
        )

    def get_tool_results_token_estimate(self, *, uncompacted_only: bool = False) -> int:
        """Conservatively estimate context tokens without a provider tokenizer."""
        return sum(
            estimate_tokens(_tool_result_context(result))
            for index, result in enumerate(self.tool_call_results)
            if not uncompacted_only or index not in self.compacted_tool_result_indexes
        )

    def get_tool_results_for_compaction(
        self,
        *,
        max_total_tokens: int,
        max_result_tokens: int,
    ) -> list[dict[str, Any]]:
        """Return one bounded batch containing only never-compacted results."""
        results: list[dict[str, Any]] = []
        used_tokens = 0
        for index, result in enumerate(self.tool_call_results):
            if index in self.compacted_tool_result_indexes:
                continue

            result_str = truncate_to_token_budget(
                _serialize_tool_result(result.result),
                max_result_tokens,
            )
            args = truncate_to_token_budget(
                json.dumps(result.args, ensure_ascii=False, default=str),
                min(10_000, max_result_tokens),
            )
            item = {
                "result_index": index,
                "id": result.id,
                "name": result.name,
                "args": args,
                "result": result_str,
            }
            item_tokens = estimate_tokens(
                json.dumps(item, ensure_ascii=False, default=str)
            )
            if results and used_tokens + item_tokens > max_total_tokens:
                break
            results.append(item)
            used_tokens += item_tokens
            if used_tokens >= max_total_tokens:
                break
        return results

    def apply_compacted_results(
        self, compacted_results: list["CompactedToolResult"]
    ) -> int:
        """Summarize matching raw results in place, at most once per result.

        Invalid, duplicate, or omitted model entries leave the original result intact.
        Updating in place also preserves the informational-results references.
        """
        applied = 0
        for compacted in compacted_results:
            index = compacted.result_index
            if (
                index < 0
                or index >= len(self.tool_call_results)
                or index in self.compacted_tool_result_indexes
            ):
                continue
            original = self.tool_call_results[index]
            if original.name != compacted.name or not compacted.summary.strip():
                continue
            original.result = compacted.summary.strip()
            self.compacted_tool_result_indexes.add(index)
            applied += 1
        return applied

    def get_evidence_size(self) -> int:
        """Calculate the total character size of all evidence"""
        total_size = 0
        for evidence in self.evidence.values():
            for snippet in evidence.content:
                total_size += len(snippet)
        return total_size

    def get_evidence_token_estimate(self) -> int:
        """Estimate the context occupied by collected paper evidence."""
        return sum(
            estimate_tokens(snippet)
            for evidence in self.evidence.values()
            for snippet in evidence.content
        )

    def apply_compacted_evidence(
        self, compacted_evidence: dict[str, list[str]]
    ) -> None:
        """Replace evidence with compacted versions from LLM compaction"""
        # Clear existing evidence and load compacted version
        self.evidence.clear()
        for document_id, snippets in compacted_evidence.items():
            self.evidence[document_id] = PaperEvidence(
                document_id=document_id, content=snippets
            )


class CompactedToolResult(BaseModel):
    """A single compacted tool result"""

    result_index: int = Field(
        ge=0,
        description="The stable result_index supplied in the compaction input",
    )
    name: str = Field(description="The tool/function name that was called")
    summary: str = Field(
        min_length=1,
        max_length=1_000,
        description="Concise summary of the result, preserving key information",
    )


class ToolResultCompactionResponse(BaseModel):
    """Response structure for tool result compaction"""

    compacted_results: list[CompactedToolResult] = Field(
        default_factory=list,
        description="List of compacted tool results with summaries",
    )


class SummaryCitationMarker(BaseModel):
    """A citation marker in a summary pointing to an original snippet."""

    marker: int = Field(description="The [@n] marker number used in the summary")
    original_snippet_index: int = Field(
        description="Index of the original snippet this marker references"
    )


class PaperEvidenceSummary(BaseModel):
    """Summary of evidence from a single paper."""

    document_id: str = Field(description="The paper ID")
    summary: str = Field(
        description="Concise summary with [@n] markers referencing original snippets"
    )
    citations: list[SummaryCitationMarker] = Field(
        default_factory=list,
        description="Mapping of [@n] markers to original snippet indices",
    )


class EvidenceSummaryResponse(BaseModel):
    """Response for evidence compaction - one summary per paper."""

    papers: list[PaperEvidenceSummary] = Field(
        default_factory=list,
        description="List of paper summaries. You may omit papers with no relevant evidence.",
    )


class EvidenceCompactionResponse(BaseModel):
    """Response structure for evidence compaction before chat response.

    The format matches ToolRunState.get_evidence_dict() output:
    Dict[str, List[str]] mapping document_id to list of evidence strings.
    """

    compacted_evidence: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping of paper IDs to their compacted evidence snippets. Each paper should have a reduced list of summarized evidence strings that preserve key findings, quotes, and data points.",
    )
