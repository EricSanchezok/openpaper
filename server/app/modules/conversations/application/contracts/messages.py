import re
import uuid
from enum import Enum
from typing import Any

from app.shared.domain.enums import ReasoningLevel
from app.modules.papers.application.contracts.citation import CitationResult
from app.modules.papers.application.contracts.extraction import ToolCall, ToolCallResult
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResponseStyle(str, Enum):
    NORMAL = "normal"
    CONCISE = "concise"
    DETAILED = "detailed"


class ConversationMessageRequest(BaseModel):
    """One stable message contract for every conversation scope."""

    model_config = ConfigDict(extra="forbid")

    user_query: str = Field(min_length=1, max_length=20_000)
    user_references: list[str] | None = Field(default=None, max_length=50)
    style: ResponseStyle | None = ResponseStyle.NORMAL
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

    @field_validator("user_references")
    @classmethod
    def validate_reference_lengths(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(len(item) > 5_000 for item in value):
            raise ValueError("Reference text exceeds maximum length")
        return value


class Evidence(BaseModel):
    """Model for managing evidence gathered from papers"""

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


class EvidenceCollection(BaseModel):
    """Collection of evidence from multiple papers"""

    evidence: dict[str, Evidence] = Field(
        default_factory=dict, description="Mapping of paper IDs to their evidence"
    )
    previous_tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="List of previous tool calls made during evidence gathering",
    )
    tool_call_results: list[ToolCallResult] = Field(
        default_factory=list,
        description="List of tool call results for proper multi-turn function calling",
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

    def add_artifact(self, artifact: CitationResult) -> None:
        """Record a first-party artifact (e.g. a resolved citation)."""
        self.artifacts.append(artifact)

    def get_artifacts(self) -> list[CitationResult]:
        return self.artifacts

    def to_trace_dict(self) -> dict[str, Any] | None:
        """Compact trajectory of this turn for user-facing inspection: the tool
        calls made and, for any citation subagent runs, their internal steps."""
        tool_calls = [
            {"name": tc.name, "args": tc.args} for tc in self.previous_tool_calls
        ]
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
            return None
        return {"tool_calls": tool_calls, "citations": citations}

    def load_from_dict(self, evidence_dict: dict[str, list[str]]) -> None:
        """Load evidence from a dictionary format"""
        for document_id, content in evidence_dict.items():
            self.evidence[document_id] = Evidence(
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
            self.evidence[document_id] = Evidence(document_id=document_id, content=[])
        self.evidence[document_id].add_content(
            content, with_line_numbers=preserve_line_numbers
        )

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the collection"""
        self.previous_tool_calls.append(tool_call)

    def add_tool_call_result(
        self,
        tool_call: ToolCall,
        result: str | list[Any] | dict[str, Any] | None,
    ) -> None:
        """Add a tool call result for proper multi-turn function calling"""
        self.tool_call_results.append(
            ToolCallResult(
                id=tool_call.id,
                name=tool_call.name,
                args=tool_call.args,
                result=result,
            )
        )

    def get_tool_call_results(self) -> list[ToolCallResult]:
        """Get all tool call results for passing to LLM"""
        return self.tool_call_results

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

    def has_previous_tool_calls(self) -> bool:
        """Check if there are any previous tool calls"""
        return bool(self.previous_tool_calls)

    def get_tool_results_size(self) -> int:
        """Calculate the total character size of all tool call results"""
        import json

        total_size = 0
        for result in self.tool_call_results:
            result_value = result.result
            if isinstance(result_value, (dict, list)):
                total_size += len(json.dumps(result_value))
            elif result_value is not None:
                total_size += len(str(result_value))
        return total_size

    def get_tool_results_for_compaction(self) -> list[dict[str, Any]]:
        """Get tool results in a format suitable for LLM compaction"""
        import json

        results = []
        for result in self.tool_call_results:
            result_value = result.result
            if isinstance(result_value, (dict, list)):
                result_str = json.dumps(result_value)
            elif result_value is not None:
                result_str = str(result_value)
            else:
                result_str = "None"

            results.append(
                {
                    "id": result.id or "",
                    "name": result.name,
                    "result": result_str[
                        :10000
                    ],  # Truncate very long individual results
                }
            )
        return results

    def apply_compacted_results(
        self, compacted_results: list["CompactedToolResult"]
    ) -> None:
        """Replace tool call results with compacted versions, preserving original args"""
        # Build a lookup of original args by id
        original_args_by_id = {r.id: r.args for r in self.tool_call_results if r.id}

        self.tool_call_results = [
            ToolCallResult(
                id=cr.id,
                name=cr.name,
                args=original_args_by_id.get(cr.id, {}),
                result=cr.summary,
            )
            for cr in compacted_results
        ]

    def get_evidence_size(self) -> int:
        """Calculate the total character size of all evidence"""
        total_size = 0
        for evidence in self.evidence.values():
            for snippet in evidence.content:
                total_size += len(snippet)
        return total_size

    def apply_compacted_evidence(
        self, compacted_evidence: dict[str, list[str]]
    ) -> None:
        """Replace evidence with compacted versions from LLM compaction"""
        # Clear existing evidence and load compacted version
        self.evidence.clear()
        for document_id, snippets in compacted_evidence.items():
            self.evidence[document_id] = Evidence(
                document_id=document_id, content=snippets
            )


class CompactedToolResult(BaseModel):
    """A single compacted tool result"""

    id: str = Field(description="The original tool call ID")
    name: str = Field(description="The tool/function name that was called")
    summary: str = Field(
        description="Concise summary of the result, preserving key information"
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

    The format matches EvidenceCollection.get_evidence_dict() output:
    Dict[str, List[str]] mapping document_id to list of evidence strings.
    """

    compacted_evidence: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Mapping of paper IDs to their compacted evidence snippets. Each paper should have a reduced list of summarized evidence strings that preserve key findings, quotes, and data points.",
    )
