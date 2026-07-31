from __future__ import annotations

from uuid import uuid4

from app.llm.backend import LLMResponse
from app.llm.conversation_tool_loop import ConversationToolLoop
from app.modules.conversations.application.chat import (
    ConversationChatScope,
    ConversationContextSnapshot,
)
from app.modules.conversations.application.contracts.messages import (
    CompactedToolResult,
    ToolRunState,
)
from app.modules.papers.application.contracts.extraction import ToolCall
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.modules.integrations.connectors.infrastructure.mcp import (
    ResolvedConnectorToolSet,
)
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import WorkspacePermission
from app.shared.domain.enums import ConversationScopeType
from app.tooling import ToolAccess, ToolExecutionContext, ToolOutcome
from app.tooling.workspace import CONVERSATION_TOOL_PROFILE
import pytest


class Catalog:
    @staticmethod
    def provider_declarations(access: ToolAccess) -> list[dict[str, object]]:
        assert access.profile_name == CONVERSATION_TOOL_PROFILE
        return [{"name": "create_project", "parameters": {"type": "object"}}]

    @staticmethod
    def is_available(access: ToolAccess, name: str) -> bool:
        return (
            name == "search_papers" and WorkspacePermission.READ in access.permissions
        )

    @staticmethod
    def profile_tool_names(_profile_name: str) -> frozenset[str]:
        return frozenset({"create_project", "search_papers", "finish_tool_use"})


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
        self.contexts: list[ToolExecutionContext] = []

    async def dispatch(
        self,
        *,
        name: str,
        context: ToolExecutionContext,
        **_kwargs: object,
    ) -> ToolOutcome:
        self.calls.append(name)
        self.contexts.append(context)
        return ToolOutcome(
            payload={"project_id": str(uuid4())},
            action={"kind": "project_created"},
        )


class NoConnectorTools:
    async def resolve(self, **_kwargs: object) -> ResolvedConnectorToolSet:
        return ResolvedConnectorToolSet()


def test_control_result_is_not_informational_answer_context() -> None:
    state = ToolRunState()
    finish = ToolCall(id="finish", name="finish_tool_use", args={})
    state.add_tool_outcome(
        finish,
        ToolOutcome(payload={"completed": True}, stop=True),
    )

    assert state.has_answer_material() is False

    connector_call = ToolCall(id="remote", name="web_search", args={"query": "RAG"})
    state.add_tool_outcome(
        connector_call,
        ToolOutcome(payload={"results": ["source"]}),
    )

    assert state.has_answer_material() is True
    assert [item.name for item in state.observations] == ["web_search"]


def test_tool_result_compaction_is_incremental_and_never_recompacts_summary() -> None:
    state = ToolRunState()
    first = ToolCall(id="first", name="search", args={"query": "one"})
    second = ToolCall(id="second", name="extract", args={"url": "two"})
    state.add_tool_outcome(first, ToolOutcome(payload={"raw": "first result"}))
    state.add_tool_outcome(second, ToolOutcome(payload={"raw": "second result"}))

    assert (
        state.apply_compacted_results(
            [
                CompactedToolResult(
                    result_index=0,
                    name="search",
                    loop_summary="first summary",
                    materials=[{"content": {"finding": "first"}}],
                )
            ]
        )
        == 1
    )
    pending = state.get_tool_results_for_compaction(
        max_total_tokens=10_000,
        max_result_tokens=5_000,
    )

    assert [item["result_index"] for item in pending] == [1]
    assert state.tool_call_results[0].result == "first summary"
    assert state.observations[0].materials == [{"finding": "first"}]

    assert (
        state.apply_compacted_results(
            [
                CompactedToolResult(
                    result_index=0,
                    name="search",
                    loop_summary="summary of the summary",
                    materials=[{"content": {"finding": "wrong"}}],
                ),
                CompactedToolResult(
                    result_index=1,
                    name="extract",
                    loop_summary="second summary",
                    materials=[{"content": {"finding": "second"}}],
                ),
            ]
        )
        == 1
    )
    assert state.tool_call_results[0].result == "first summary"
    assert state.tool_call_results[1].result == "second summary"


def test_tool_result_compaction_preserves_omitted_and_invalid_results() -> None:
    state = ToolRunState()
    call = ToolCall(id=None, name="search", args={"query": "one"})
    state.add_tool_outcome(call, ToolOutcome(payload={"raw": "must survive"}))

    assert state.apply_compacted_results([]) == 0
    assert (
        state.apply_compacted_results(
            [
                CompactedToolResult(
                    result_index=0,
                    name="wrong_tool",
                    loop_summary="incorrect replacement",
                    materials=[{"content": {"finding": "incorrect"}}],
                )
            ]
        )
        == 0
    )
    assert state.tool_call_results[0].result == {"raw": "must survive"}


def test_tool_loop_model_view_bounds_results_without_mutating_observations() -> None:
    state = ToolRunState()
    for index in range(2):
        call = ToolCall(id=str(index), name="search", args={"query": str(index)})
        state.add_tool_outcome(
            call,
            ToolOutcome(payload={"raw": "x" * 10_000}),
        )

    bounded = state.tool_call_results_for_model(max_tokens=100)

    assert len(bounded) == 2
    assert all(len(str(item.result)) < 10_000 for item in bounded)
    assert state.observations[0].payload == {"raw": "x" * 10_000}


@pytest.mark.asyncio
async def test_successful_action_does_not_fall_back_to_paper_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = ActionDispatcher()
    runtime = object.__new__(ConversationToolLoop)
    runtime._catalog = Catalog()  # type: ignore[assignment]
    runtime._dispatcher = dispatcher
    runtime._connector_tools = NoConnectorTools()  # type: ignore[assignment]
    runtime._operation_factory = OperationContextFactory()
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
    conversation_id = uuid4()
    turn_id = uuid4()
    request_operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=RequestReference(uuid4()),
            conversation_id=conversation_id,
            turn_id=turn_id,
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
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
                tool_permissions=frozenset(WorkspacePermission),
            ),
            conversation_id=conversation_id,
            turn_id=turn_id,
            client_ip="test",
            request_operation=request_operation,
            turn_correlation_id=request_operation.trace.correlation_id,
            user_operation_id=request_operation.trace.operation_id,
        )
    ]

    completed = next(event for event in events if event["type"] == "tool_run_completed")
    state = completed["content"]
    assert isinstance(state, ToolRunState)
    assert state.action_results == [{"kind": "project_created"}]
    assert dispatcher.calls == ["create_project"]
    tool_operation = dispatcher.contexts[0].operation
    assert tool_operation.initiated_by is OperationInitiator.AGENT
    assert tool_operation.trace.correlation_id == request_operation.trace.correlation_id
    assert tool_operation.trace.causation_id == request_operation.trace.operation_id
    assert tool_operation.origin is request_operation.origin
