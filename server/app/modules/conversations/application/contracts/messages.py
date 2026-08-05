import json
import uuid
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.shared.application.context_budget import (
    estimate_tokens,
    truncate_to_token_budget,
)
from app.shared.domain.enums import ReasoningLevel
from app.shared.domain import JsonValue
from app.modules.papers.application.contracts.citation import CitationResult
from app.modules.papers.application.contracts.extraction import ToolCall, ToolCallResult
from app.tooling.contracts import ToolOutcome, ToolSourceCandidate
from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class ConversationStreamStartEvent(BaseModel):
    type: Literal["start"] = "start"
    conversation_id: uuid.UUID
    turn_id: uuid.UUID


class ConversationActivity(BaseModel):
    """One sanitized, user-inspectable tool lifecycle entry."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=200)
    sequence: int = Field(ge=1)
    category: Literal["search", "read", "workspace_action", "connector"]
    state: Literal["running", "succeeded", "failed"]
    tool_name: str = Field(min_length=1, max_length=128)
    subject: str | None = Field(default=None, max_length=240)
    connector_name: str | None = Field(default=None, max_length=80)
    source_count: int | None = Field(default=None, ge=0)
    artifact_count: int | None = Field(default=None, ge=0)


class ConversationCitationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_count: int = Field(ge=0)
    annotation_count: int = Field(ge=0)
    rejected_source_count: int = Field(ge=0)


class ConversationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activities: list[ConversationActivity] = Field(default_factory=list)
    citation_summary: ConversationCitationSummary | None = None


class ConversationStreamActivityEvent(BaseModel):
    type: Literal["activity"] = "activity"
    activity: ConversationActivity


class ConversationStreamContentDeltaEvent(BaseModel):
    type: Literal["content_delta"] = "content_delta"
    delta: str


class ConversationStreamReferencesEvent(BaseModel):
    type: Literal["references"] = "references"
    references: dict[str, JsonValue]


class ConversationStreamCompleteEvent(BaseModel):
    type: Literal["complete"] = "complete"
    turn_id: uuid.UUID
    trace: ConversationTrace | None = None
    artifacts: list[dict[str, JsonValue]] = Field(default_factory=list)


class ConversationStreamErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    error: dict[str, JsonValue]


ConversationStreamEvent = Annotated[
    ConversationStreamStartEvent
    | ConversationStreamActivityEvent
    | ConversationStreamContentDeltaEvent
    | ConversationStreamReferencesEvent
    | ConversationStreamCompleteEvent
    | ConversationStreamErrorEvent,
    Field(discriminator="type"),
]


class ConversationStreamEventSchema(RootModel[ConversationStreamEvent]):
    """Public schema for the JSON payload carried by each SSE event."""


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
    locale: Literal["en", "zh-CN"]
    time_zone: str = Field(min_length=1, max_length=100)
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

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("time_zone must be a valid IANA time zone") from exc
        return value


class ToolObservation(BaseModel):
    """One successful, immutable tool result retained for the final answer."""

    result_index: int = Field(ge=0)
    name: str
    args: dict[str, Any]
    payload: JsonValue
    sources: list[ToolSourceCandidate] = Field(default_factory=list)
    materials: list[JsonValue] | None = None
    action_only: bool = False


class ToolRunState(BaseModel):
    """Typed state produced by one Conversation tool loop."""

    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="List of previous tool calls made during evidence gathering",
    )
    tool_call_results: list[ToolCallResult] = Field(
        default_factory=list,
        description="List of tool call results for proper multi-turn function calling",
    )
    observations: list[ToolObservation] = Field(
        default_factory=list,
        description="Successful tool observations available to the final answer.",
    )
    compacted_tool_result_indexes: set[int] = Field(
        default_factory=set,
        exclude=True,
        description="Internal indexes of raw tool results already summarized once.",
    )
    failed_observations: int = 0
    artifacts: list[CitationResult] = Field(
        default_factory=list,
        description="First-party artifacts produced during gathering (e.g. citations)",
    )
    action_results: list[dict[str, JsonValue]] = Field(
        default_factory=list,
        description="Successful state-changing tool outcomes.",
    )
    citation_metrics: dict[str, int] | None = Field(default=None, exclude=True)

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
        if (
            not tool_calls
            and not citations
            and not self.action_results
            and not self.citation_metrics
        ):
            return None
        trace = {
            "tool_calls": tool_calls,
            "citations": citations,
            "actions": self.action_results,
        }
        if self.citation_metrics is not None:
            trace["citation_summary"] = self.citation_metrics
        return trace

    def add_tool_call(self, tool_call: ToolCall) -> None:
        """Add a tool call to the collection"""
        self.tool_calls.append(tool_call)

    def add_tool_outcome(self, tool_call: ToolCall, outcome: ToolOutcome) -> None:
        """Record one successful result for both the loop and final answer."""
        result_index = len(self.tool_call_results)
        item = ToolCallResult(
            id=tool_call.id,
            name=tool_call.name,
            args=tool_call.args,
            result=outcome.payload,
        )
        self.tool_call_results.append(item)
        if not outcome.stop:
            self.observations.append(
                ToolObservation(
                    result_index=result_index,
                    name=tool_call.name,
                    args=tool_call.args,
                    payload=outcome.payload,
                    sources=list(outcome.sources),
                    action_only=outcome.action is not None and not outcome.sources,
                )
            )
        if outcome.action is not None:
            self.action_results.append(outcome.action)

    def add_tool_error(self, tool_call: ToolCall, result: JsonValue) -> None:
        result_index = len(self.tool_call_results)
        self.tool_call_results.append(
            ToolCallResult(
                id=tool_call.id,
                name=tool_call.name,
                args=tool_call.args,
                result=result,
            )
        )
        self.compacted_tool_result_indexes.add(result_index)
        self.failed_observations += 1

    def tool_call_results_for_model(self, *, max_tokens: int) -> list[ToolCallResult]:
        """Return a fair bounded view without mutating retained observations."""
        if self.get_tool_results_token_estimate() <= max_tokens:
            return self.tool_call_results
        per_result = max(1, max_tokens // max(1, len(self.tool_call_results)))
        bounded: list[ToolCallResult] = []
        for result in self.tool_call_results:
            metadata_tokens = estimate_tokens(
                json.dumps(
                    {
                        "id": result.id,
                        "name": result.name,
                        "args": result.args,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            )
            result_budget = max(1, per_result - metadata_tokens)
            bounded.append(
                result.model_copy(
                    update={
                        "result": truncate_to_token_budget(
                            _serialize_tool_result(result.result),
                            result_budget,
                        )
                    }
                )
            )
        return bounded

    def has_answer_material(self) -> bool:
        return any(not item.action_only for item in self.observations)

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
        The matching observation keeps its one-time materialization sidecar.
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
            if original.name != compacted.name or not compacted.loop_summary.strip():
                continue
            original.result = compacted.loop_summary.strip()
            observation = next(
                (
                    item
                    for item in self.observations
                    if item.result_index == compacted.result_index
                ),
                None,
            )
            if observation is not None:
                observation.materials = [item.content for item in compacted.materials]
            self.compacted_tool_result_indexes.add(index)
            applied += 1
        return applied


class CompactedMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: JsonValue


class CompactedToolResult(BaseModel):
    """A single compacted tool result"""

    result_index: int = Field(
        ge=0,
        description="The stable result_index supplied in the compaction input",
    )
    name: str = Field(description="The tool/function name that was called")
    loop_summary: str = Field(
        min_length=1,
        max_length=1_000,
        description="Concise summary of the result, preserving key information",
    )
    materials: list[CompactedMaterial] = Field(min_length=1, max_length=50)


class ToolResultCompactionResponse(BaseModel):
    """Response structure for tool result compaction"""

    compacted_results: list[CompactedToolResult] = Field(
        default_factory=list,
        description="List of compacted tool results with summaries",
    )
