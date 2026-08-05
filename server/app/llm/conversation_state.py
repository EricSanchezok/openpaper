"""Server-owned state accumulated during one Conversation Agent run."""

from __future__ import annotations

from typing import Any

from app.modules.papers.application.contracts.citation import CitationResult
from app.shared.domain import JsonValue
from app.tooling.contracts import ToolOutcome, ToolSourceCandidate
from pydantic import BaseModel, Field


class ToolObservation(BaseModel):
    """One successful, immutable tool result retained for answer grounding."""

    result_index: int = Field(ge=0)
    args: dict[str, Any]
    payload: JsonValue
    sources: list[ToolSourceCandidate] = Field(default_factory=list)
    action_only: bool = False


class ConversationAgentState(BaseModel):
    """Evidence and artifacts retained outside Pydantic AI's model history."""

    observations: list[ToolObservation] = Field(default_factory=list)
    failed_observations: int = 0
    artifacts: list[CitationResult] = Field(default_factory=list)
    action_results: list[dict[str, JsonValue]] = Field(default_factory=list)

    def add_artifact(self, artifact: CitationResult) -> None:
        self.artifacts.append(artifact)

    def add_tool_outcome(
        self,
        arguments: dict[str, Any],
        outcome: ToolOutcome,
    ) -> int:
        """Record one successful result and return its stable run-local index."""
        result_index = len(self.observations) + self.failed_observations
        self.observations.append(
            ToolObservation(
                result_index=result_index,
                args=arguments,
                payload=outcome.payload,
                sources=list(outcome.sources),
                action_only=outcome.action is not None and not outcome.sources,
            )
        )
        if outcome.action is not None:
            self.action_results.append(outcome.action)
        return result_index

    def add_tool_error(self) -> None:
        self.failed_observations += 1
