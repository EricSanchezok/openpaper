from __future__ import annotations

from uuid import uuid4

from app.llm.backend import LLMResponse
from app.llm.conversation_tool_loop import ConversationToolLoop
from app.modules.conversations.application.chat import (
    ConversationChatScope,
    ConversationContextSnapshot,
)
from app.modules.conversations.application.contracts.messages import ToolRunState
from app.modules.papers.application.contracts.extraction import ToolCall
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import Actor
from app.shared.domain.enums import ConversationScopeType
from app.tooling import ToolOutcome
from app.tooling.workspace import CONVERSATION_TOOL_PROFILE
import pytest


class Catalog:
    @staticmethod
    def provider_declarations(profile: str) -> list[dict[str, object]]:
        assert profile == CONVERSATION_TOOL_PROFILE
        return [{"name": "create_project", "parameters": {"type": "object"}}]


class Executor:
    def __init__(self) -> None:
        self._results = iter(
            [
                [],
                ConversationContextSnapshot(
                    papers=[],
                    projects=[],
                    available_document_count=0,
                ),
            ]
        )

    def query(self, _operation: object) -> object:
        return next(self._results)


class ActionDispatcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def dispatch(self, *, name: str, **_kwargs: object) -> ToolOutcome:
        self.calls.append(name)
        return ToolOutcome(
            payload={"project_id": str(uuid4())},
            action={"kind": "project_created"},
        )


@pytest.mark.asyncio
async def test_successful_action_does_not_fall_back_to_paper_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = ActionDispatcher()
    runtime = object.__new__(ConversationToolLoop)
    runtime._catalog = Catalog()  # type: ignore[assignment]
    runtime._dispatcher = dispatcher
    responses = iter(
        [
            LLMResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="create_project",
                        args={"name": "New Project"},
                    )
                ],
            ),
            LLMResponse(text=""),
        ]
    )
    monkeypatch.setattr(runtime, "generate_content", lambda **_kwargs: next(responses))
    monkeypatch.setattr(
        "app.llm.conversation_tool_loop.track_event",
        lambda *_args, **_kwargs: None,
    )

    events = [
        event
        async for event in runtime.run_tools(
            question="Create a project called New Project",
            current_user=Actor(
                id=7,
                email="researcher@example.com",
                status="active",
                email_verified=True,
            ),
            executor=Executor(),  # type: ignore[arg-type]
            conversation_scope=ConversationChatScope(
                scope_type=ConversationScopeType.GLOBAL,
                project_id=None,
                document_id=None,
                paper_context=LibraryPaperCollection(),
            ),
            conversation_id=uuid4(),
            turn_id=uuid4(),
            client_ip="test",
        )
    ]

    completed = next(
        event for event in events if event["type"] == "tool_run_completed"
    )
    state = completed["content"]
    assert isinstance(state, ToolRunState)
    assert state.action_results == [{"kind": "project_created"}]
    assert dispatcher.calls == ["create_project"]
