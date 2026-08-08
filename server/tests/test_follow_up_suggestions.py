from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from app.bootstrap.workflows.conversation_suggestions import (
    ConversationSuggestionWorkflow,
)
from app.llm.follow_up_suggestions import (
    FollowUpSuggestionSet,
    build_follow_up_prompt,
)
from app.modules.conversations.application.suggestions import (
    SuggestionClaim,
    SuggestionSeed,
    SuggestionStatus,
)
from app.shared.application import Actor
from pydantic import ValidationError


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _seed(response_id: UUID | None = None) -> SuggestionSeed:
    return SuggestionSeed(
        response_id=response_id or uuid4(),
        user_query="How does retrieval work?",
        final_answer="The selected answer explains grounded retrieval.",
        locale="en",
        source_titles=("Verified source",),
    )


class _SuggestionCapability:
    def __init__(self, executor: _BoundaryExecutor, seed: SuggestionSeed) -> None:
        self._executor = executor
        self._seed = seed
        self.status: SuggestionStatus | Literal["idle"] = "idle"
        self.suggestions: tuple[str, ...] = ()

    def claim(self, **_: object) -> SuggestionClaim:
        assert self._executor.active
        if self.status != "idle":
            return SuggestionClaim(
                response_id=self._seed.response_id,
                status=self.status,
                suggestions=self.suggestions,
            )
        self.status = "pending"
        return SuggestionClaim(
            response_id=self._seed.response_id,
            status="pending",
            seed=self._seed,
        )

    def complete(
        self, *, suggestions: tuple[str, str, str], **_: object
    ) -> SuggestionClaim:
        assert self._executor.active
        self.status = "completed"
        self.suggestions = suggestions
        return SuggestionClaim(
            response_id=self._seed.response_id,
            status="completed",
            suggestions=suggestions,
        )

    def fail(self, **_: object) -> SuggestionClaim:
        assert self._executor.active
        self.status = "failed"
        return SuggestionClaim(response_id=self._seed.response_id, status="failed")

    @property
    def seed(self) -> SuggestionSeed:
        return self._seed


class _Capabilities:
    def __init__(self, suggestions: _SuggestionCapability) -> None:
        self.conversation_suggestions = suggestions


class _BoundaryExecutor:
    def __init__(self, seed: SuggestionSeed) -> None:
        self.active = False
        self.command_count = 0
        self.suggestions = _SuggestionCapability(self, seed)
        self.capabilities = _Capabilities(self.suggestions)

    def command(self, callback: Callable[[Any], Any]) -> Any:
        assert not self.active
        self.active = True
        self.command_count += 1
        try:
            return callback(self.capabilities)
        finally:
            self.active = False

    def query(self, callback: Callable[[Any], Any]) -> Any:
        return self.command(callback)

    async def command_async(self, callback: Callable[[Any], Awaitable[Any]]) -> Any:
        assert not self.active
        self.active = True
        try:
            return await callback(self.capabilities)
        finally:
            self.active = False


class _Generator:
    def __init__(
        self,
        executor: _BoundaryExecutor,
        values: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._executor = executor
        self._values = values or ["Deepen?", "Verify?", "Apply?"]
        self._error = error
        self.call_count = 0

    async def generate(self, seed: SuggestionSeed) -> list[str]:
        assert not self._executor.active
        assert seed is self._executor.suggestions.seed
        self.call_count += 1
        if self._error is not None:
            raise self._error
        return self._values


def test_structured_suggestions_are_normalized_and_unique() -> None:
    suggestions = FollowUpSuggestionSet(
        deepen="  What   evidence is missing?  ",
        compare_or_verify="How does this compare?",
        practical_application="How would I apply it?",
    )

    assert suggestions.deepen == "What evidence is missing?"

    with pytest.raises(ValidationError):
        FollowUpSuggestionSet(
            deepen="Same?",
            compare_or_verify="same?",
            practical_application="Apply?",
        )


def test_prompt_contains_only_the_explicit_suggestion_seed() -> None:
    prompt = build_follow_up_prompt(_seed())

    assert "How does retrieval work?" in prompt
    assert "The selected answer explains grounded retrieval." in prompt
    assert "Verified source" in prompt
    assert "tool_name" not in prompt
    assert "trace" not in prompt


@pytest.mark.asyncio
async def test_workflow_generates_outside_transactions_and_persists_once() -> None:
    seed = _seed()
    executor = _BoundaryExecutor(seed)
    generator = _Generator(executor)
    workflow = ConversationSuggestionWorkflow(
        executor=executor,
        generator=generator,
    )

    first = await workflow.generate(
        actor=_actor(), conversation_id=uuid4(), response_id=seed.response_id
    )
    replay = await workflow.generate(
        actor=_actor(), conversation_id=uuid4(), response_id=seed.response_id
    )

    assert first.status == "completed"
    assert first.suggestions == ["Deepen?", "Verify?", "Apply?"]
    assert replay == first
    assert generator.call_count == 1
    assert executor.command_count == 3


@pytest.mark.asyncio
async def test_workflow_records_generation_failure_without_partial_results() -> None:
    seed = _seed()
    executor = _BoundaryExecutor(seed)
    workflow = ConversationSuggestionWorkflow(
        executor=executor,
        generator=_Generator(executor, error=RuntimeError("provider secret")),
    )

    response = await workflow.generate(
        actor=_actor(), conversation_id=uuid4(), response_id=seed.response_id
    )

    assert response.status == "failed"
    assert response.suggestions == []
    assert executor.suggestions.suggestions == ()
