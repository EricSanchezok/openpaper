from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from app.bootstrap.adapters.conversation_repository import conversation_repository
from app.bootstrap.workflows.citation import CitationWorkflow
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.database.models import Conversation
from app.llm.backend import LLMResponse
from app.llm.conversation_tool_loop import ConversationToolLoop
from app.main import app
from app.modules.conversations.application.chat import (
    ConversationChatScope,
    ConversationContextSnapshot,
)
from app.modules.conversations.application.contracts.conversations import (
    ConversationCreateRequest,
    ConversationSummaryResponse,
    ConversationToolPermissionsRequest,
)
from app.modules.papers.application.contracts.search import LibraryPaperCollection
from app.modules.integrations.connectors.infrastructure.mcp import (
    ResolvedConnectorToolSet,
)
from app.shared.application import (
    Actor,
    ConversationOrigin,
    CredentialKind,
    CredentialRef,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.shared.domain import (
    WORKSPACE_PERMISSION_ORDER,
    AppError,
    FailureKind,
    WorkspacePermission,
    normalize_workspace_permissions,
    ordered_workspace_permissions,
)
from app.shared.domain.enums import ConversationScopeType
from app.tooling import (
    ToolAccess,
    ToolExecutionContext,
    ToolCatalog,
    ToolDefinition,
    ToolDispatcher,
    ToolExecutionKind,
    ToolOutcome,
    ToolProfile,
)
from app.tooling.workspace import (
    CONVERSATION_TOOL_PROFILE,
    MCP_TOOL_PROFILE,
    build_workspace_tool_catalog,
)
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

ResultT = TypeVar("ResultT")


class RequiredInput(BaseModel):
    value: str


def _handler(
    _capabilities: object,
    _context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = RequiredInput.model_validate(arguments)
    return ToolOutcome(payload={"value": parsed.value})


async def _workflow_handler(
    _context: ToolExecutionContext,
    arguments: BaseModel,
    _invocation_key: str,
) -> ToolOutcome:
    parsed = RequiredInput.model_validate(arguments)
    return ToolOutcome(payload={"value": parsed.value})


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _request_operation(
    *,
    conversation_id: UUID | None = None,
    turn_id: UUID | None = None,
) -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=ConversationOrigin(
            request=RequestReference(uuid4()),
            conversation_id=conversation_id or uuid4(),
            turn_id=turn_id or uuid4(),
        ),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


def _context() -> ToolExecutionContext:
    operation_factory = OperationContextFactory()
    request_operation = _request_operation()
    return ToolExecutionContext(
        actor=_actor(),
        operation=operation_factory.child(
            request_operation,
            initiated_by=OperationInitiator.AGENT,
        ),
        paper_collection=LibraryPaperCollection(),
        anchor_document_id=None,
        invocation_id="permission-test",
        client_ip="test",
    )


@pytest.mark.parametrize(
    "values, expected",
    [
        ([], frozenset()),
        (["read"], frozenset({WorkspacePermission.READ})),
        (
            ["delete", WorkspacePermission.READ, "delete"],
            frozenset(
                {
                    WorkspacePermission.READ,
                    WorkspacePermission.DELETE,
                }
            ),
        ),
    ],
)
def test_workspace_permission_normalization(
    values: list[WorkspacePermission | str],
    expected: frozenset[WorkspacePermission],
) -> None:
    assert normalize_workspace_permissions(values) == expected


def test_workspace_permissions_always_serialize_in_canonical_order() -> None:
    assert ordered_workspace_permissions(["delete", "write", "read", "write"]) == [
        WorkspacePermission.READ,
        WorkspacePermission.WRITE,
        WorkspacePermission.DELETE,
    ]
    assert WORKSPACE_PERMISSION_ORDER == (
        WorkspacePermission.READ,
        WorkspacePermission.WRITE,
        WorkspacePermission.DELETE,
    )


def test_workspace_permission_normalization_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        normalize_workspace_permissions(["admin"])


@pytest.mark.parametrize(
    ("execution", "handler", "workflow_handler"),
    [
        (ToolExecutionKind.QUERY, _handler, None),
        (ToolExecutionKind.COMMAND, _handler, None),
        (ToolExecutionKind.WORKFLOW, None, _workflow_handler),
    ],
)
def test_every_business_tool_must_declare_exactly_one_permission(
    execution: ToolExecutionKind,
    handler: object,
    workflow_handler: object,
) -> None:
    with pytest.raises(ValueError, match="require one workspace permission"):
        ToolDefinition(
            name="business_tool",
            description="Business tool",
            input_model=RequiredInput,
            execution=execution,
            required_permission=None,
            handler=handler,  # type: ignore[arg-type]
            workflow_handler=workflow_handler,  # type: ignore[arg-type]
        )


def test_control_tool_cannot_require_permission_or_execute_a_handler() -> None:
    with pytest.raises(ValueError, match="cannot require workspace permission"):
        ToolDefinition(
            name="finish",
            description="Finish",
            input_model=RequiredInput,
            execution=ToolExecutionKind.CONTROL,
            required_permission=WorkspacePermission.READ,
        )
    with pytest.raises(ValueError, match="cannot define handlers"):
        ToolDefinition(
            name="finish",
            description="Finish",
            input_model=RequiredInput,
            execution=ToolExecutionKind.CONTROL,
            required_permission=None,
            handler=_handler,
        )


def test_handler_shape_must_match_execution_kind() -> None:
    with pytest.raises(ValueError, match="exactly one handler"):
        ToolDefinition(
            name="read_tool",
            description="Read",
            input_model=RequiredInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
        )
    with pytest.raises(ValueError, match="exactly one workflow handler"):
        ToolDefinition(
            name="workflow_tool",
            description="Workflow",
            input_model=RequiredInput,
            execution=ToolExecutionKind.WORKFLOW,
            required_permission=WorkspacePermission.WRITE,
            handler=_handler,
        )


def test_catalog_combines_profile_and_permissions_and_always_keeps_control() -> None:
    definitions = [
        ToolDefinition(
            name="read_tool",
            description="Read",
            input_model=RequiredInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_handler,
        ),
        ToolDefinition(
            name="write_tool",
            description="Write",
            input_model=RequiredInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_handler,
        ),
        ToolDefinition(
            name="finish",
            description="Finish",
            input_model=RequiredInput,
            execution=ToolExecutionKind.CONTROL,
            required_permission=None,
        ),
    ]
    catalog = ToolCatalog(
        definitions,
        [
            ToolProfile(
                name="conversation",
                tool_names=frozenset({"read_tool", "write_tool", "finish"}),
            ),
            ToolProfile(name="mcp", tool_names=frozenset({"read_tool"})),
        ],
    )

    conversation_access = ToolAccess(
        profile_name="conversation",
        permissions=frozenset({WorkspacePermission.WRITE}),
    )
    assert [
        definition.name for definition in catalog.definitions_for(conversation_access)
    ] == ["finish", "write_tool"]
    assert [
        declaration["name"]
        for declaration in catalog.provider_declarations(conversation_access)
    ] == ["finish", "write_tool"]
    assert catalog.is_available(conversation_access, "finish")
    assert not catalog.is_available(conversation_access, "read_tool")

    mcp_access = ToolAccess(
        profile_name="mcp",
        permissions=frozenset({WorkspacePermission.READ}),
    )
    assert [definition.name for definition in catalog.definitions_for(mcp_access)] == [
        "read_tool"
    ]
    assert not catalog.is_available(mcp_access, "finish")


class _UntouchableExecutor:
    def __init__(self) -> None:
        self.queries = 0
        self.commands = 0

    def query(self, _operation: Callable[[object], ResultT]) -> ResultT:
        self.queries += 1
        raise AssertionError("authorization must happen before query or ledger access")

    def command(self, _operation: Callable[[object], ResultT]) -> ResultT:
        self.commands += 1
        raise AssertionError(
            "authorization must happen before command or ledger access"
        )

    async def command_async(
        self,
        _operation: Callable[[object], ResultT],
    ) -> ResultT:
        raise AssertionError("authorization must happen before async execution")


@pytest.mark.asyncio
async def test_dispatcher_hides_unknown_profile_external_and_unauthorized_tools() -> (
    None
):
    protected_handler = MagicMock(side_effect=AssertionError("handler must not run"))
    definitions = [
        ToolDefinition(
            name="protected_tool",
            description="Protected",
            input_model=RequiredInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.DELETE,
            handler=protected_handler,
        ),
        ToolDefinition(
            name="outside_tool",
            description="Outside",
            input_model=RequiredInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=protected_handler,
        ),
    ]
    executor = _UntouchableExecutor()
    dispatcher = ToolDispatcher(
        catalog=ToolCatalog(
            definitions,
            [
                ToolProfile(
                    name="conversation",
                    tool_names=frozenset({"protected_tool"}),
                )
            ],
        ),
        executor=executor,  # type: ignore[arg-type]
    )
    access = ToolAccess(profile_name="conversation", permissions=frozenset())

    errors: list[AppError] = []
    for name in ("missing_tool", "outside_tool", "protected_tool"):
        with pytest.raises(AppError) as exc_info:
            await dispatcher.dispatch(
                name=name,
                raw_arguments={},
                context=_context(),
                access=access,
            )
        errors.append(exc_info.value)

    assert {
        (error.kind, error.code, error.message, error.details) for error in errors
    } == {
        (
            FailureKind.NOT_FOUND,
            "tool_not_found",
            "Tool not found",
            None,
        )
    }
    assert executor.queries == 0
    assert executor.commands == 0
    protected_handler.assert_not_called()


def test_workspace_tool_permission_mapping_is_exact() -> None:
    expected = {
        WorkspacePermission.READ: {
            "search_papers",
            "get_paper",
            "get_paper_abstract",
            "get_paper_content",
            "search_paper_content",
            "get_paper_content_range",
            "get_paper_download_url",
            "list_projects",
            "get_project",
            "list_project_papers",
            "list_paper_projects",
            "list_library_papers",
            "get_library_paper",
            "list_highlights",
            "list_jobs",
            "get_job",
        },
        WorkspacePermission.WRITE: {
            "get_paper_citation",
            "create_project",
            "update_project",
            "add_papers_to_project",
            "update_library_paper",
            "collect_project_paper_to_library",
            "ingest_paper_from_url",
            "create_highlight",
            "update_highlight",
            "create_annotation_comment",
            "update_annotation_comment",
        },
        WorkspacePermission.DELETE: {
            "delete_project",
            "remove_paper_from_project",
            "remove_library_paper",
            "delete_highlight",
            "delete_annotation_comment",
        },
    }
    catalog = build_workspace_tool_catalog(
        ingestion=MagicMock(spec=PaperIngestionWorkflow),
        citations=MagicMock(spec=CitationWorkflow),
    )
    full_conversation_access = ToolAccess(
        profile_name=CONVERSATION_TOOL_PROFILE,
        permissions=frozenset(WORKSPACE_PERMISSION_ORDER),
    )
    definitions = {
        definition.name: definition
        for definition in catalog.definitions_for(full_conversation_access)
    }

    actual = {
        permission: {
            definition.name
            for definition in definitions.values()
            if definition.required_permission is permission
        }
        for permission in WORKSPACE_PERMISSION_ORDER
    }
    assert actual == expected
    assert definitions["finish_tool_use"].required_permission is None
    assert definitions["finish_tool_use"].execution is ToolExecutionKind.CONTROL
    assert set(definitions) == set().union(*expected.values()) | {"finish_tool_use"}

    full_mcp_access = ToolAccess(
        profile_name=MCP_TOOL_PROFILE,
        permissions=frozenset(WORKSPACE_PERMISSION_ORDER),
    )
    assert {
        definition.name for definition in catalog.definitions_for(full_mcp_access)
    } == set().union(*expected.values())


def test_conversation_permission_contracts_normalize_and_allow_empty() -> None:
    default_request = ConversationCreateRequest(scope_type="global")
    assert default_request.tool_permissions is None

    custom_request = ConversationCreateRequest(
        scope_type="global",
        tool_permissions=["delete", "read", "delete"],
    )
    assert custom_request.tool_permissions == [
        WorkspacePermission.READ,
        WorkspacePermission.DELETE,
    ]
    assert (
        ConversationCreateRequest(
            scope_type="global",
            tool_permissions=[],
        ).tool_permissions
        == []
    )
    assert ConversationToolPermissionsRequest(
        permissions=["write", "read", "write"],
    ).permissions == [
        WorkspacePermission.READ,
        WorkspacePermission.WRITE,
    ]
    with pytest.raises(ValidationError):
        ConversationToolPermissionsRequest(permissions=["admin"])


def test_openapi_requires_permissions_only_on_conversation_detail() -> None:
    schemas = app.openapi()["components"]["schemas"]
    detail = schemas["ConversationDetailResponse"]
    summary = schemas["ConversationSummaryResponse"]
    create = schemas["ConversationCreateRequest"]

    assert "tool_permissions" in detail["properties"]
    assert "tool_permissions" in detail["required"]
    assert "tool_permissions" not in summary["properties"]
    assert "tool_permissions" in create["properties"]
    assert "tool_permissions" not in create.get("required", [])
    assert (
        "/api/v1/conversations/{conversation_id}/tool-permissions"
        in app.openapi()["paths"]
    )


def test_permission_update_is_owned_locked_canonical_and_scope_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = Conversation(
        id=uuid4(),
        title="Lost scope",
        user_id=7,
        scope_type="project",
        project_id=None,
        context_deleted_at=datetime.now(timezone.utc),
        tool_permissions=["read", "write"],
    )
    db = MagicMock(spec=Session)
    db.scalar.return_value = conversation
    monkeypatch.setattr(
        "app.bootstrap.adapters.conversation_repository."
        "conversation_policy.require_can_continue",
        MagicMock(side_effect=AssertionError("scope access is irrelevant")),
    )

    write = conversation_repository.update_tool_permissions(
        db,
        conversation_id=conversation.id,
        user_id=7,
        request=ConversationToolPermissionsRequest(
            permissions=["delete", "read", "delete"]
        ),
    )
    result = write.value

    assert write.changed is True
    assert result.permissions == [
        WorkspacePermission.READ,
        WorkspacePermission.DELETE,
    ]
    assert conversation.tool_permissions == ["read", "delete"]
    assert "FOR UPDATE" in str(db.scalar.call_args.args[0])
    db.flush.assert_called_once_with()
    db.commit.assert_not_called()


def test_permission_field_is_detail_only_at_the_python_contract_boundary() -> None:
    assert "tool_permissions" not in ConversationSummaryResponse.model_fields


class _RuntimeCatalog:
    def __init__(self) -> None:
        self.declaration_access: ToolAccess | None = None
        self.availability_access: ToolAccess | None = None

    def provider_declarations(self, access: ToolAccess) -> list[dict[str, object]]:
        self.declaration_access = access
        return [{"name": "finish_tool_use", "parameters": {"type": "object"}}]

    def is_available(self, access: ToolAccess, name: str) -> bool:
        assert name == "search_papers"
        self.availability_access = access
        return False


class _RuntimeExecutor:
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


class _RuntimeConnectorTools:
    def __init__(self) -> None:
        self.permissions: frozenset[WorkspacePermission] | None = None

    async def resolve(
        self,
        *,
        permissions: frozenset[WorkspacePermission],
        **_kwargs: object,
    ) -> ResolvedConnectorToolSet:
        self.permissions = permissions
        return ResolvedConnectorToolSet()


@pytest.mark.asyncio
async def test_runtime_without_read_permission_never_runs_fallback_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _RuntimeCatalog()
    dispatcher = MagicMock()
    runtime = object.__new__(ConversationToolLoop)
    runtime._catalog = catalog  # type: ignore[assignment]
    runtime._dispatcher = dispatcher
    connector_tools = _RuntimeConnectorTools()
    runtime._connector_tools = connector_tools  # type: ignore[assignment]
    runtime._operation_factory = OperationContextFactory()
    runtime.generate_content = MagicMock(return_value=LLMResponse(text=""))
    keyword_extractor = MagicMock(side_effect=AssertionError("fallback must not run"))
    runtime._extract_search_keywords = keyword_extractor
    monkeypatch.setattr(
        "app.llm.conversation_tool_loop.track_event",
        lambda *_args, **_kwargs: None,
    )
    conversation_id = uuid4()
    turn_id = uuid4()
    request_operation = _request_operation(
        conversation_id=conversation_id,
        turn_id=turn_id,
    )

    events = [
        event
        async for event in runtime.run_tools(
            question="What does my library say?",
            current_user=_actor(),
            executor=_RuntimeExecutor(),  # type: ignore[arg-type]
            conversation_scope=ConversationChatScope(
                scope_type=ConversationScopeType.GLOBAL,
                project_id=None,
                document_id=None,
                paper_context=LibraryPaperCollection(),
                tool_permissions=frozenset({WorkspacePermission.WRITE}),
            ),
            conversation_id=conversation_id,
            turn_id=turn_id,
            client_ip="test",
            request_operation=request_operation,
            turn_correlation_id=request_operation.trace.correlation_id,
            user_operation_id=request_operation.trace.operation_id,
        )
    ]

    assert events[-1]["type"] == "tool_run_completed"
    assert catalog.declaration_access is catalog.availability_access
    assert catalog.declaration_access == ToolAccess(
        profile_name=CONVERSATION_TOOL_PROFILE,
        permissions=frozenset({WorkspacePermission.WRITE}),
    )
    assert connector_tools.permissions == frozenset({WorkspacePermission.WRITE})
    keyword_extractor.assert_not_called()
    dispatcher.dispatch.assert_not_called()
