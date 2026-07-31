from uuid import UUID, uuid4
from unittest.mock import MagicMock

from app.bootstrap.workflows.citation import CitationWorkflow
from app.llm.backend import LLMResponse
from app.llm.citation_recovery import MetadataRecoveryAgent
from app.main import app
from app.modules.integrations.connectors.infrastructure.mcp import (
    ResolvedConnectorToolSet,
)
from app.modules.papers.application.contracts.citation import (
    CitationData,
    CitationResult,
)
from app.modules.papers.application.contracts.extraction import ToolCall
from app.modules.papers.domain.citations import CitationFields
from app.shared.application import (
    Actor,
    CredentialKind,
    CredentialRef,
    HttpOrigin,
    OperationContext,
    OperationContextFactory,
    OperationInitiator,
    RequestReference,
)
from app.transport.http.public_v1.documents.router import get_document_citation


def actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
        is_active=True,
    )


def operation() -> OperationContext:
    return OperationContextFactory().root(
        initiated_by=OperationInitiator.USER,
        origin=HttpOrigin(RequestReference(uuid4())),
        credential=CredentialRef(CredentialKind.CLOUD_SESSION),
    )


class CachedCitationCapability:
    def __init__(self, fields: CitationFields) -> None:
        self.fields = fields

    def read(self, **_kwargs: object) -> CitationFields:
        return self.fields


class CachedCapabilities:
    def __init__(self, fields: CitationFields) -> None:
        self.citations = CachedCitationCapability(fields)


class QueryExecutor:
    def __init__(self, fields: CitationFields) -> None:
        self._capabilities = CachedCapabilities(fields)
        self.query_count = 0

    def query(self, callback: object) -> object:
        self.query_count += 1
        return callback(self._capabilities)  # type: ignore[operator]

    def command(self, _callback: object) -> object:
        raise AssertionError("cached citation must not start a command")


class UnexpectedProvider:
    def deterministic(self, **_kwargs: object) -> object:
        raise AssertionError("cached citation must not call a provider")

    def agentic(self, **_kwargs: object) -> object:
        raise AssertionError("cached citation must not call a provider")


def test_cached_citation_does_not_call_external_metadata_paths() -> None:
    executor = QueryExecutor(
        CitationFields(
            title="A Paper",
            authors=["A. Author"],
            publish_date="2025-01-01",
            journal="Journal",
        )
    )
    workflow = CitationWorkflow(
        executor=executor,  # type: ignore[arg-type]
        provider=UnexpectedProvider(),  # type: ignore[arg-type]
        operation_factory=OperationContextFactory(),
    )

    result = workflow.run(
        actor=actor(),
        operation=operation(),
        document_id=uuid4(),
        style="APA",
    )

    assert result.method == "cached"
    assert result.data.title == "A Paper"
    assert executor.query_count == 1


def test_citation_is_one_shared_public_paper_capability() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/papers/{document_id}/citation" in paths
    assert (
        paths["/api/v1/papers/{document_id}/citation"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/CitationResult"
    )


def test_http_citation_delegates_to_short_transaction_workflow() -> None:
    document_id = uuid4()
    request_operation = operation()
    expected = CitationResult(
        document_id=str(document_id),
        preferred_style="APA",
        style_display="APA 7th Edition",
        data=CitationData(document_id=str(document_id), title="A Paper"),
        method="cached",
    )

    class Workflow:
        def run(
            self,
            *,
            actor: Actor,
            operation: OperationContext,
            document_id: UUID,
            style: str,
            project_id: UUID | None,
        ) -> CitationResult:
            assert actor.id == 7
            assert operation is request_operation
            assert style == "APA"
            assert project_id is None
            assert str(document_id) == expected.document_id
            return expected

    result = get_document_citation(
        document_id=document_id,
        style="APA",
        project_id=None,
        workflow=Workflow(),  # type: ignore[arg-type]
        current_user=actor(),
        operation=request_operation,
    )

    assert result == expected


def test_citation_recovery_stops_when_no_connector_tools_are_available() -> None:
    class Resolver:
        def resolve_sync(self, **_kwargs: object) -> ResolvedConnectorToolSet:
            return ResolvedConnectorToolSet()

    recovery = object.__new__(MetadataRecoveryAgent)
    recovery._connector_tools = Resolver()  # type: ignore[assignment]
    generate = MagicMock(side_effect=AssertionError("LLM must not guess metadata"))
    recovery.generate_content = generate

    result = recovery._run_research_loop(
        actor(),
        CitationFields(title="A Paper", authors=["A. Author"]),
        ["journal"],
        [],
    )

    assert result is None
    generate.assert_not_called()


def test_citation_recovery_rejects_submission_without_remote_results() -> None:
    class Resolver:
        def resolve_sync(self, **_kwargs: object) -> ResolvedConnectorToolSet:
            return ResolvedConnectorToolSet(
                declarations=(
                    {
                        "name": "remote_search",
                        "description": "Search",
                        "parameters": {"type": "object"},
                    },
                )
            )

    recovery = object.__new__(MetadataRecoveryAgent)
    recovery._connector_tools = Resolver()  # type: ignore[assignment]
    recovery.generate_content = MagicMock(
        return_value=LLMResponse(
            text="",
            tool_calls=[
                ToolCall(
                    id="submit",
                    name="submit_findings",
                    args={"journal": "Guessed Journal", "confidence": 0.99},
                )
            ],
        )
    )

    result = recovery._run_research_loop(
        actor(),
        CitationFields(title="A Paper", authors=["A. Author"]),
        ["journal"],
        [],
    )

    assert result is None
