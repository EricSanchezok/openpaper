from __future__ import annotations

import re
import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.llm.conversation_agent import ScholensConversationAgent
from app.modules.conversations.application.chat import (
    ChatPaperSnapshot,
    ConversationChatScope,
    ConversationContextSnapshot,
)
from app.modules.conversations.application.contracts.messages import (
    ConversationActivity,
    ConversationMessageRequest,
    ConversationTrace,
)
from app.modules.conversations.application.contracts.answer_packet import (
    ReferenceBundle,
)
from app.modules.integrations.connectors.infrastructure.mcp import (
    ResolvedConnectorToolSet,
)
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import AppError, FailureKind, WorkspacePermission
from app.shared.domain.enums import ConversationScopeType
from app.tooling import (
    DocumentSourceCandidate,
    ToolCatalog,
    ToolDefinition,
    ToolExecutionKind,
    ToolOutcome,
    ToolProfile,
)
from app.tooling.workspace import CONVERSATION_TOOL_PROFILE
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel


class SearchInput(BaseModel):
    query: str


def _unused_handler(*_args: object, **_kwargs: object) -> ToolOutcome:
    raise AssertionError("the runtime must use ToolDispatcher")


def _catalog() -> ToolCatalog[Any]:
    return ToolCatalog(
        [
            ToolDefinition(
                name="search_papers",
                description="Search the authorized paper collection.",
                input_model=SearchInput,
                execution=ToolExecutionKind.QUERY,
                required_permission=WorkspacePermission.READ,
                handler=_unused_handler,
                activity_subject_field="query",
            )
        ],
        [
            ToolProfile(
                name=CONVERSATION_TOOL_PROFILE,
                tool_names=frozenset({"search_papers"}),
            )
        ],
    )


class _ChatData:
    @staticmethod
    def history(**_kwargs: object) -> list[object]:
        return []


class _Capabilities:
    conversation_chat_data = _ChatData()


class _Executor:
    def query(self, operation: Any) -> Any:
        return operation(_Capabilities())


class _ConnectorTools:
    async def resolve(self, **_kwargs: object) -> ResolvedConnectorToolSet:
        return ResolvedConnectorToolSet()


class _Dispatcher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.document_id = uuid4()

    async def dispatch(
        self, *, name: str, raw_arguments: dict[str, Any], **_kwargs: Any
    ) -> ToolOutcome:
        self.calls.append((name, raw_arguments))
        if self.fail:
            raise AppError(
                code="search_temporarily_unavailable",
                message="Search is unavailable",
                kind=FailureKind.DEPENDENCY_FAILURE,
            )
        return ToolOutcome(
            payload={"results": [{"title": "A grounded paper"}]},
            sources=(
                DocumentSourceCandidate(
                    document_id=self.document_id,
                    title="A grounded paper",
                    excerpt="Validated evidence about chain-of-thought compression.",
                ),
            ),
        )


class _Clock:
    @staticmethod
    def now() -> datetime:
        return datetime(2026, 8, 5, 16, 30, tzinfo=timezone.utc)


def _request_operation(conversation_id: UUID, turn_id: UUID) -> Any:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=RequestReference(uuid4()),
            conversation_id=conversation_id,
            turn_id=turn_id,
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _scope() -> ConversationChatScope:
    return ConversationChatScope(
        scope_type=ConversationScopeType.GLOBAL,
        project_id=None,
        document_id=None,
        paper_context=LibraryPaperCollection(),
        tool_permissions=frozenset({WorkspacePermission.READ}),
        title_is_default=True,
    )


def _snapshot(dispatcher: _Dispatcher) -> ConversationContextSnapshot:
    return ConversationContextSnapshot(
        papers=[
            ChatPaperSnapshot(
                document_id=dispatcher.document_id,
                title="A grounded paper",
                abstract="Validated abstract.",
                raw_content="Validated evidence about chain-of-thought compression.",
                keywords=None,
                authors=["Researcher"],
                publish_date=None,
            )
        ],
        projects=[],
        available_document_count=1,
    )


async def _events(
    *,
    model: Any,
    dispatcher: _Dispatcher,
    query: str,
    locale: str = "zh-CN",
    time_zone: str = "Asia/Shanghai",
    scope: ConversationChatScope | None = None,
) -> list[dict[str, object]]:
    runtime = ScholensConversationAgent(
        catalog=_catalog(),
        dispatcher=dispatcher,  # type: ignore[arg-type]
        connector_tools=_ConnectorTools(),  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
        clock=_Clock(),
        model_factory=lambda _level: model,
    )
    conversation_id = uuid4()
    turn_id = uuid4()
    operation = _request_operation(conversation_id, turn_id)
    request = ConversationMessageRequest(
        turn_id=turn_id,
        user_query=query,
        locale=locale,  # type: ignore[arg-type]
        time_zone=time_zone,
    )
    return [
        event
        async for event in runtime.stream(
            request=request,
            actor=Actor(
                id=7,
                email="researcher@example.com",
                status="active",
                email_verified=True,
            ),
            executor=_Executor(),  # type: ignore[arg-type]
            conversation_scope=scope or _scope(),
            context_snapshot=_snapshot(dispatcher),
            conversation_id=conversation_id,
            client_ip="127.0.0.1",
            request_operation=operation,
            correlation_id=operation.trace.correlation_id,
            user_operation_id=operation.trace.operation_id,
            mentioned_highlights=None,
        )
    ]


def _activities(trace: ConversationTrace) -> list[ConversationActivity]:
    return [entry for entry in trace.entries if entry.kind == "activity"]


def _final_text(events: list[dict[str, object]]) -> str:
    return "".join(
        str(event["delta"])
        for event in events
        if event["type"] == "assistant_item_delta"
    )


@pytest.fixture(autouse=True)
def _disable_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.llm.conversation_agent.settle_token_usage", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        "app.llm.conversation_agent.track_event", lambda *_args, **_kwargs: None
    )


@pytest.mark.asyncio
async def test_zero_tool_answer_uses_injected_local_date() -> None:
    seen_instructions: list[str] = []

    async def direct_answer(
        _messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str]:
        seen_instructions.append(info.instructions or "")
        yield "今天是星期四。"

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=direct_answer),
        dispatcher=dispatcher,
        query="今天星期几？",
    )

    assert dispatcher.calls == []
    assert [event["type"] for event in events] == [
        "assistant_item_start",
        "assistant_item_delta",
        "assistant_item_complete",
        "complete",
    ]
    assert events[2]["item"]["phase"] == "final"  # type: ignore[index]
    assert "2026-08-06" in seen_instructions[0]
    assert "Asia/Shanghai" in seen_instructions[0]
    assert events[-1]["trace"] is None


@pytest.mark.asyncio
async def test_text_before_tool_is_completed_as_progress_before_activity() -> None:
    async def staged_answer(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            yield "I will inspect the available research."
            yield {
                0: DeltaToolCall(
                    name="search_papers",
                    json_args='{"query":"reasoning compression"}',
                    tool_call_id="search-progress",
                )
            }
            return
        yield "Final answer."

    events = await _events(
        model=FunctionModel(stream_function=staged_answer),
        dispatcher=_Dispatcher(),
        query="Research this topic",
        locale="en",
        time_zone="UTC",
    )

    types = [event["type"] for event in events]
    progress_complete_index = next(
        index
        for index, event in enumerate(events)
        if event["type"] == "assistant_item_complete"
        and event["item"]["phase"] == "progress"  # type: ignore[index]
    )
    first_activity_index = types.index("activity")
    assert progress_complete_index < first_activity_index
    assert events[progress_complete_index]["item"]["content"] == (  # type: ignore[index]
        "I will inspect the available research."
    )
    trace = events[-1]["trace"]
    assert isinstance(trace, ConversationTrace)
    assert [(entry.kind, entry.sequence) for entry in trace.entries] == [
        ("progress", 1),
        ("activity", 2),
    ]
    final = [
        event["item"]
        for event in events
        if event["type"] == "assistant_item_complete"
        and event["item"]["phase"] == "final"  # type: ignore[index]
    ]
    assert final == [
        {
            "id": final[0]["id"],
            "sequence": 3,
            "phase": "final",
            "content": "Final answer.",
        }
    ]


@pytest.mark.asyncio
async def test_research_tool_streams_sanitized_activity_and_references() -> None:
    async def research_answer(
        messages: list[ModelMessage], info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        has_result = any(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if not has_result:
            yield {
                0: DeltaToolCall(
                    name="search_papers",
                    json_args='{"query":"reasoning compression"}',
                    tool_call_id="search-1",
                )
            }
            return
        nonce_match = re.search(r"SCHOLENS_CITE:([0-9a-f]+):1", info.instructions or "")
        assert nonce_match is not None
        yield f"Grounded claim[[SCHOLENS_CITE:{nonce_match.group(1)}:1]]"

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=research_answer),
        dispatcher=dispatcher,
        query="研究思维链压缩技术",
    )

    activities = [event["activity"] for event in events if event["type"] == "activity"]
    assert activities == [
        ConversationActivity(
            id="search-1",
            sequence=1,
            category="search",
            state="running",
            subject="reasoning compression",
        ),
        ConversationActivity(
            id="search-1",
            sequence=1,
            category="search",
            state="succeeded",
            subject="reasoning compression",
            source_count=1,
            artifact_count=0,
        ),
    ]
    assert dispatcher.calls == [("search_papers", {"query": "reasoning compression"})]
    assert _final_text(events) == "Grounded claim"
    references = next(
        event["references"] for event in events if event["type"] == "references"
    )
    assert isinstance(references, ReferenceBundle)
    assert len(references.sources) == 1
    trace = events[-1]["trace"]
    assert isinstance(trace, ConversationTrace)
    assert trace.citation_summary is not None
    assert trace.citation_summary.source_count == 1


@pytest.mark.asyncio
async def test_tool_failure_can_continue_to_a_natural_answer() -> None:
    dispatcher = _Dispatcher(fail=True)
    events = await _events(
        model=TestModel(
            call_tools=["search_papers"],
            custom_output_text="I could not search, but here is what I can explain.",
        ),
        dispatcher=dispatcher,
        query="Explain the topic even if search is unavailable",
        locale="en",
        time_zone="UTC",
    )

    trace = events[-1]["trace"]
    assert isinstance(trace, ConversationTrace)
    assert _activities(trace)[-1].state == "failed"
    assert any(event["type"] == "assistant_item_delta" for event in events)


@pytest.mark.asyncio
async def test_multiple_tools_preserve_order_and_terminal_state() -> None:
    async def multi_tool_answer(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        result_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if result_count < 2:
            sequence = result_count + 1
            yield f"Research stage {sequence}."
            yield {
                0: DeltaToolCall(
                    name="search_papers",
                    json_args=f'{{"query":"topic {sequence}"}}',
                    tool_call_id=f"search-{sequence}",
                )
            }
            return
        yield "Combined answer."

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=multi_tool_answer),
        dispatcher=dispatcher,
        query="Compare two research directions",
        locale="en",
        time_zone="UTC",
    )

    trace = events[-1]["trace"]
    assert isinstance(trace, ConversationTrace)
    assert [(entry.kind, entry.sequence) for entry in trace.entries] == [
        ("progress", 1),
        ("activity", 2),
        ("progress", 3),
        ("activity", 4),
    ]
    assert [activity.sequence for activity in _activities(trace)] == [2, 4]
    assert [activity.state for activity in _activities(trace)] == [
        "succeeded",
        "succeeded",
    ]
    assert [arguments["query"] for _, arguments in dispatcher.calls] == [
        "topic 1",
        "topic 2",
    ]
    completed_items = [
        event["item"] for event in events if event["type"] == "assistant_item_complete"
    ]
    assert [item["phase"] for item in completed_items] == [
        "progress",
        "progress",
        "final",
    ]
    assert [item["content"] for item in completed_items] == [
        "Research stage 1.",
        "Research stage 2.",
        "Combined answer.",
    ]
    assert "tool_name" not in str(events)


@pytest.mark.asyncio
async def test_duplicate_tool_call_is_blocked_before_dispatch() -> None:
    async def duplicate_answer(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        result_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        if result_count < 2:
            sequence = result_count + 1
            yield {
                0: DeltaToolCall(
                    name="search_papers",
                    json_args='{"query":"same topic"}',
                    tool_call_id=f"search-{sequence}",
                )
            }
            return
        yield "Used the first result."

    dispatcher = _Dispatcher()
    events = await _events(
        model=FunctionModel(stream_function=duplicate_answer),
        dispatcher=dispatcher,
        query="Search once, not twice",
        locale="en",
        time_zone="UTC",
    )

    assert len(dispatcher.calls) == 1
    trace = events[-1]["trace"]
    assert isinstance(trace, ConversationTrace)
    assert [activity.state for activity in _activities(trace)] == [
        "succeeded",
        "failed",
    ]


@pytest.mark.asyncio
async def test_unauthorized_tool_is_not_exposed_or_dispatched() -> None:
    dispatcher = _Dispatcher()
    events = await _events(
        model=TestModel(call_tools="all", custom_output_text="No tool available."),
        dispatcher=dispatcher,
        query="Search my papers",
        locale="en",
        time_zone="UTC",
        scope=ConversationChatScope(
            scope_type=ConversationScopeType.PROJECT,
            project_id=uuid4(),
            document_id=None,
            paper_context=LibraryPaperCollection(),
            tool_permissions=frozenset({WorkspacePermission.WRITE}),
            title_is_default=False,
        ),
    )

    assert dispatcher.calls == []
    assert events[-1]["trace"] is None


@pytest.mark.asyncio
async def test_cancellation_propagates_without_becoming_a_product_error() -> None:
    entered = asyncio.Event()

    async def blocked_answer(
        _messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[str]:
        entered.set()
        await asyncio.Event().wait()
        yield "unreachable"

    dispatcher = _Dispatcher()
    task = asyncio.create_task(
        _events(
            model=FunctionModel(stream_function=blocked_answer),
            dispatcher=dispatcher,
            query="Wait",
        )
    )
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_agent_enforces_maximum_tool_call_budget() -> None:
    async def endless_tools(
        messages: list[ModelMessage], _info: AgentInfo
    ) -> AsyncIterator[dict[int, DeltaToolCall]]:
        result_count = sum(
            isinstance(part, ToolReturnPart)
            for message in messages
            for part in message.parts
        )
        yield {
            0: DeltaToolCall(
                name="search_papers",
                json_args=f'{{"query":"topic {result_count}"}}',
                tool_call_id=f"search-{result_count}",
            )
        }

    with pytest.raises(AppError):
        await _events(
            model=FunctionModel(stream_function=endless_tools),
            dispatcher=_Dispatcher(),
            query="Never stop searching",
            locale="en",
            time_zone="UTC",
        )


def test_request_rejects_non_iana_time_zone() -> None:
    with pytest.raises(ValueError, match="valid IANA time zone"):
        ConversationMessageRequest(
            turn_id=uuid4(),
            user_query="What time is it?",
            locale="en",
            time_zone="Shanghai",
        )
