"""Canonical Scholens research-workspace tools.

Names, schemas, descriptions, handlers, and profile membership live here once.
Agent and MCP transports only render or dispatch this catalog.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import cast
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
from app.bootstrap.workflows.citation import CitationWorkflow
from app.modules.jobs.application.contracts import JobResponse
from app.modules.papers.application.contracts.documents import (
    DocumentMetadataOverrides,
    LibraryPaperUpdateRequest,
)
from app.modules.papers.application.contracts.search import (
    PaperSearchFilters,
    PaperSearchRequest,
)
from app.modules.papers.application.contracts.uploads import UploadAcceptedResponse
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
)
from app.modules.research.application.contracts import (
    CreateAnnotationCommentRequest,
    CreateHighlightThreadRequest,
    DeleteHighlightThreadRequest,
    UpdateAnnotationCommentRequest,
    UpdateHighlightThreadRequest,
)
from app.shared.domain import (
    AppError,
    FailureKind,
    JsonValue,
    WorkspacePermission,
)
from app.shared.domain.enums import JobOperation, PaperStatus, RoleType
from app.tooling.catalog import ToolCatalog, ToolProfile
from app.tooling.contracts import (
    DocumentSourceCandidate,
    ToolExecutionContext,
    ToolDefinition,
    ToolExecutionKind,
    ToolOutcome,
)
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, model_validator

CONVERSATION_TOOL_PROFILE = "conversation"
MCP_TOOL_PROFILE = "mcp"
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def _json(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _JSON_VALUE.validate_python(value)


def _document_source(
    *,
    document_id: UUID,
    excerpt: str,
    title: str | None = None,
    authors: list[str] | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
) -> DocumentSourceCandidate:
    locator: dict[str, JsonValue] = {}
    if start_line is not None:
        locator["start_line"] = start_line
    if end_line is not None:
        locator["end_line"] = end_line
    return DocumentSourceCandidate(
        document_id=document_id,
        excerpt=excerpt,
        title=title,
        authors=tuple(authors or ()),
        locator=locator or None,
    )


def _source_from_numbered_line(
    *, document_id: UUID, value: str, title: str | None = None
) -> DocumentSourceCandidate:
    match = re.match(r"^(\d+):\s*(.*)$", value, flags=re.DOTALL)
    if match is None:
        return _document_source(
            document_id=document_id,
            excerpt=value,
            title=title,
        )
    line_number = int(match.group(1))
    return _document_source(
        document_id=document_id,
        excerpt=match.group(2),
        title=title,
        start_line=line_number,
        end_line=line_number,
    )


def _require_paper(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    document_id: UUID,
) -> None:
    capabilities.paper_collection_access(
        actor=context.actor,
        collection=context.paper_collection,
        document_id=document_id,
        anchor_document_id=context.anchor_document_id,
    )


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID


class SearchPapersInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=2, max_length=1_000)


class SearchPaperContentInput(DocumentInput):
    query: str = Field(min_length=1, max_length=2_000)


class PaperContentRangeInput(DocumentInput):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> PaperContentRangeInput:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class PaperCitationInput(DocumentInput):
    style: str = Field(default="APA", min_length=1, max_length=100)


class ListProjectsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: int = Field(default=50, ge=1, le=100)


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID


class UpdateProjectInput(ProjectUpdateRequest):
    project_id: UUID


class AddPapersToProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    document_ids: list[UUID] = Field(min_length=1, max_length=120)


class ProjectPaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    document_id: UUID


class UpdateLibraryPaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    status: PaperStatus | None = None
    metadata_overrides: DocumentMetadataOverrides | None = None


class CollectProjectPaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_project_id: UUID
    document_id: UUID


class IngestPaperFromUrlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    project_id: UUID | None = None


class CreateHighlightInput(CreateHighlightThreadRequest):
    document_id: UUID


class UpdateHighlightInput(UpdateHighlightThreadRequest):
    highlight_id: UUID


class DeleteHighlightInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    highlight_id: UUID
    delete_annotations: bool = False


class CreateAnnotationCommentInput(CreateAnnotationCommentRequest):
    highlight_id: UUID


class UpdateAnnotationCommentInput(UpdateAnnotationCommentRequest):
    annotation_id: UUID


class AnnotationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotation_id: UUID


class ListJobsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID | None = None
    document_id: UUID | None = None
    operation: JobOperation | None = None
    active: bool = False


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: UUID


def _search_papers(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = SearchPapersInput.model_validate(arguments)
    response = capabilities.paper_search(
        actor=context.actor,
        request=PaperSearchRequest(
            query=parsed.query,
            collection=context.paper_collection,
            filters=PaperSearchFilters(),
            limit=100,
        ),
    )
    sources: list[DocumentSourceCandidate] = []
    for item in response.items:
        sources.extend(
            _document_source(
                document_id=item.document_id,
                excerpt=snippet.text,
                title=item.title,
                authors=item.authors,
                start_line=snippet.start_line,
                end_line=snippet.end_line,
            )
            for snippet in item.snippets
            if snippet.text
        )
    return ToolOutcome(payload=_json(response), sources=tuple(sources))


def _get_paper(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    _require_paper(capabilities, context, parsed.document_id)
    return ToolOutcome(
        payload=_json(
            capabilities.paper_details(
                actor=context.actor,
                document_id=parsed.document_id,
            )
        )
    )


def _paper_content(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    document_id: UUID,
) -> tuple[str | None, str | None, str | None]:
    _require_paper(capabilities, context, document_id)
    paper = capabilities.paper_content.read(
        actor=context.actor,
        document_id=document_id,
    )
    return paper.title, paper.abstract, paper.raw_content


def _get_paper_abstract(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    title, abstract, _ = _paper_content(
        capabilities,
        context,
        parsed.document_id,
    )
    payload = {
        "document_id": str(parsed.document_id),
        "title": title,
        "abstract": abstract,
    }
    return ToolOutcome(
        payload=_json(payload),
        sources=(
            (
                _document_source(
                    document_id=parsed.document_id,
                    excerpt=abstract,
                    title=title,
                ),
            )
            if abstract
            else ()
        ),
    )


def _get_paper_content(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    title, _, content = _paper_content(
        capabilities,
        context,
        parsed.document_id,
    )
    payload = {
        "document_id": str(parsed.document_id),
        "title": title,
        "content": content,
    }
    return ToolOutcome(
        payload=_json(payload),
        sources=(
            (
                _document_source(
                    document_id=parsed.document_id,
                    excerpt=content,
                    title=title,
                ),
            )
            if content
            else ()
        ),
    )


def _search_paper_content(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = SearchPaperContentInput.model_validate(arguments)
    _require_paper(capabilities, context, parsed.document_id)
    matches = capabilities.paper_content.search_document(
        actor=context.actor,
        document_id=parsed.document_id,
        query=parsed.query,
    )
    return ToolOutcome(
        payload=_json({"document_id": str(parsed.document_id), "matches": matches}),
        sources=tuple(
            _source_from_numbered_line(
                document_id=parsed.document_id,
                value=match,
            )
            for match in matches
            if match
        ),
    )


def _get_paper_content_range(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = PaperContentRangeInput.model_validate(arguments)
    title, _, content = _paper_content(
        capabilities,
        context,
        parsed.document_id,
    )
    if not content:
        lines: list[str] = []
    else:
        source_lines = content.splitlines()
        if parsed.end_line > len(source_lines):
            raise AppError(
                kind=FailureKind.INVALID_ARGUMENT,
                code="paper_content_range_invalid",
                message="end_line exceeds paper content",
                details={"line_count": len(source_lines)},
            )
        lines = [
            f"{line_number}: {source_lines[line_number - 1]}"
            for line_number in range(parsed.start_line, parsed.end_line + 1)
        ]
    return ToolOutcome(
        payload=_json(
            {
                "document_id": str(parsed.document_id),
                "title": title,
                "start_line": parsed.start_line,
                "end_line": parsed.end_line,
                "lines": lines,
            }
        ),
        sources=tuple(
            _source_from_numbered_line(
                document_id=parsed.document_id,
                value=line,
                title=title,
            )
            for line in lines
        ),
    )


def _get_paper_download_url(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    _require_paper(capabilities, context, parsed.document_id)
    return ToolOutcome(
        payload=_json(
            capabilities.paper_download(
                actor=context.actor,
                document_id=parsed.document_id,
            )
        )
    )


def _list_projects(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ListProjectsInput.model_validate(arguments)
    return ToolOutcome(
        payload=_json(
            capabilities.projects.list(actor=context.actor, limit=parsed.limit)
        )
    )


def _get_project(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ProjectInput.model_validate(arguments)
    return ToolOutcome(
        payload=_json(
            capabilities.projects.get(
                actor=context.actor,
                project_id=parsed.project_id,
            )
        )
    )


def _create_project(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    request = ProjectCreateRequest.model_validate(arguments.model_dump())
    result = capabilities.projects.create(
        actor=context.actor,
        operation=context.operation,
        request=request,
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "project_created", "project": payload},
    )


def _update_project(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateProjectInput.model_validate(arguments)
    result = capabilities.projects.update(
        actor=context.actor,
        operation=context.operation,
        project_id=parsed.project_id,
        request=ProjectUpdateRequest.model_validate(
            parsed.model_dump(exclude={"project_id"})
        ),
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "project_updated", "project": payload},
    )


def _delete_project(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ProjectInput.model_validate(arguments)
    capabilities.projects.delete(
        actor=context.actor,
        operation=context.operation,
        project_id=parsed.project_id,
    )
    payload: dict[str, JsonValue] = {
        "deleted": True,
        "project_id": str(parsed.project_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _list_project_papers(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ProjectInput.model_validate(arguments)
    return ToolOutcome(
        payload=_json(
            capabilities.projects.documents(
                actor=context.actor,
                project_id=parsed.project_id,
                load_urls=False,
            )
        )
    )


def _add_papers_to_project(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = AddPapersToProjectInput.model_validate(arguments)
    result = capabilities.projects.add_documents(
        actor=context.actor,
        operation=context.operation,
        project_id=parsed.project_id,
        request=AddPaperToProjectRequest(document_ids=parsed.document_ids),
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={
            "kind": "papers_added_to_project",
            "project_id": str(parsed.project_id),
            "result": payload,
        },
    )


def _remove_paper_from_project(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ProjectPaperInput.model_validate(arguments)
    capabilities.projects.remove_document(
        actor=context.actor,
        operation=context.operation,
        project_id=parsed.project_id,
        document_id=parsed.document_id,
    )
    payload: dict[str, JsonValue] = {
        "removed": True,
        "project_id": str(parsed.project_id),
        "document_id": str(parsed.document_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _list_paper_projects(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    return ToolOutcome(
        payload=_json(
            capabilities.projects.projects_for_document(
                actor=context.actor,
                document_id=parsed.document_id,
            )
        )
    )


def _list_library_papers(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    del arguments
    return ToolOutcome(
        payload=_json(capabilities.paper_library.list(actor=context.actor))
    )


def _get_library_paper(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    return ToolOutcome(
        payload=_json(
            capabilities.paper_library.get(
                actor=context.actor,
                document_id=parsed.document_id,
            )
        )
    )


def _update_library_paper(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateLibraryPaperInput.model_validate(arguments)
    result = capabilities.paper_library.update(
        actor=context.actor,
        operation=context.operation,
        document_id=parsed.document_id,
        request=LibraryPaperUpdateRequest(
            status=parsed.status,
            metadata_overrides=parsed.metadata_overrides,
        ),
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "library_paper_updated", "paper": payload},
    )


def _remove_library_paper(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    capabilities.paper_library.remove(
        actor=context.actor,
        operation=context.operation,
        document_id=parsed.document_id,
    )
    payload: dict[str, JsonValue] = {
        "removed": True,
        "document_id": str(parsed.document_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _collect_project_paper_to_library(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = CollectProjectPaperInput.model_validate(arguments)
    result = capabilities.projects.collect_document(
        actor=context.actor,
        operation=context.operation,
        request=CollectPaperFromProjectRequest(
            source_project_id=parsed.source_project_id,
            document_id=parsed.document_id,
        ),
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "project_paper_collected", "result": payload},
    )


def _list_highlights(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    _require_paper(capabilities, context, parsed.document_id)
    return ToolOutcome(
        payload=_json(
            capabilities.research_items.list_document(
                actor=context.actor,
                document_id=parsed.document_id,
                highlights_only=True,
            )
        )
    )


def _create_highlight(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = CreateHighlightInput.model_validate(arguments)
    _require_paper(capabilities, context, parsed.document_id)
    request = CreateHighlightThreadRequest.model_validate(
        parsed.model_dump(exclude={"document_id"})
    )
    result = capabilities.research_items.create_highlight(
        actor=context.actor,
        operation=context.operation,
        content_role=RoleType.ASSISTANT,
        document_id=parsed.document_id,
        request=request,
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "highlight_created", "highlight": payload},
    )


def _update_highlight(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateHighlightInput.model_validate(arguments)
    result = capabilities.research_items.update_highlight(
        actor=context.actor,
        operation=context.operation,
        thread_id=parsed.highlight_id,
        request=UpdateHighlightThreadRequest.model_validate(
            parsed.model_dump(exclude={"highlight_id"})
        ),
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "highlight_updated", "highlight": payload},
    )


def _delete_highlight(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DeleteHighlightInput.model_validate(arguments)
    capabilities.research_items.delete_highlight(
        actor=context.actor,
        operation=context.operation,
        thread_id=parsed.highlight_id,
        request=DeleteHighlightThreadRequest(
            confirm_delete_replies=parsed.delete_annotations
        ),
    )
    payload: dict[str, JsonValue] = {
        "deleted": True,
        "highlight_id": str(parsed.highlight_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _create_annotation_comment(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = CreateAnnotationCommentInput.model_validate(arguments)
    result = capabilities.research_items.create_comment(
        actor=context.actor,
        operation=context.operation,
        content_role=RoleType.ASSISTANT,
        thread_id=parsed.highlight_id,
        request=CreateAnnotationCommentRequest(content=parsed.content),
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "annotation_comment_created", "annotation": payload},
    )


def _update_annotation_comment(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateAnnotationCommentInput.model_validate(arguments)
    result = capabilities.research_items.update_comment(
        actor=context.actor,
        operation=context.operation,
        comment_id=parsed.annotation_id,
        request=UpdateAnnotationCommentRequest(content=parsed.content),
    )
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "annotation_comment_updated", "annotation": payload},
    )


def _delete_annotation_comment(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = AnnotationInput.model_validate(arguments)
    capabilities.research_items.delete_comment(
        actor=context.actor,
        operation=context.operation,
        comment_id=parsed.annotation_id,
    )
    payload: dict[str, JsonValue] = {
        "deleted": True,
        "annotation_id": str(parsed.annotation_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _list_jobs(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ListJobsInput.model_validate(arguments)
    return ToolOutcome(
        payload=_json(
            capabilities.jobs.list(
                actor=context.actor,
                project_id=parsed.project_id,
                document_id=parsed.document_id,
                operation=parsed.operation,
                active=parsed.active,
            )
        )
    )


def _get_job(
    capabilities: ApplicationCapabilities,
    context: ToolExecutionContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = JobInput.model_validate(arguments)
    result: JobResponse = capabilities.jobs.get(
        actor=context.actor,
        job_id=parsed.job_id,
    )
    return ToolOutcome(payload=_json(result))


def build_workspace_tool_catalog(
    *,
    ingestion: PaperIngestionWorkflow,
    citations: CitationWorkflow,
) -> ToolCatalog[ApplicationCapabilities]:
    async def get_paper_citation(
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
    ) -> ToolOutcome:
        del invocation_key
        parsed = PaperCitationInput.model_validate(arguments)
        citation = await asyncio.to_thread(
            citations.run,
            actor=context.actor,
            operation=context.operation,
            document_id=parsed.document_id,
            style=parsed.style,
            paper_collection=context.paper_collection,
            anchor_document_id=context.anchor_document_id,
        )
        payload = cast(dict[str, JsonValue], _json(citation))
        return ToolOutcome(payload=payload, artifacts=[payload])

    async def ingest_paper_from_url(
        context: ToolExecutionContext,
        arguments: BaseModel,
        invocation_key: str,
    ) -> ToolOutcome:
        parsed = IngestPaperFromUrlInput.model_validate(arguments)
        idempotency_key = "tool:" + hashlib.sha256(invocation_key.encode()).hexdigest()
        result: UploadAcceptedResponse = await ingestion.from_url(
            actor=context.actor,
            operation=context.operation,
            url=str(parsed.url),
            project_id=parsed.project_id,
            idempotency_key=idempotency_key,
            ip_address=context.client_ip,
        )
        payload = _json(result)
        return ToolOutcome(
            payload=payload,
            action={"kind": "paper_ingestion_started", "result": payload},
        )

    definitions = [
        ToolDefinition(
            name="search_papers",
            description="Search the server-bound paper collection.",
            input_model=SearchPapersInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_search_papers,
        ),
        ToolDefinition(
            name="get_paper",
            description=(
                "Get canonical metadata for one paper in the server-bound collection."
            ),
            input_model=DocumentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_paper,
        ),
        ToolDefinition(
            name="get_paper_abstract",
            description="Get the abstract of one paper in the server-bound collection.",
            input_model=DocumentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_paper_abstract,
        ),
        ToolDefinition(
            name="get_paper_content",
            description="Read the complete extracted text of one paper.",
            input_model=DocumentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_paper_content,
        ),
        ToolDefinition(
            name="search_paper_content",
            description="Search one paper's extracted text with a regular expression.",
            input_model=SearchPaperContentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_search_paper_content,
        ),
        ToolDefinition(
            name="get_paper_content_range",
            description="Read an inclusive one-based line range from one paper.",
            input_model=PaperContentRangeInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_paper_content_range,
        ),
        ToolDefinition(
            name="get_paper_citation",
            description=(
                "Resolve bibliographic metadata for one paper and persist "
                "recovered fields."
            ),
            input_model=PaperCitationInput,
            execution=ToolExecutionKind.WORKFLOW,
            required_permission=WorkspacePermission.WRITE,
            workflow_handler=get_paper_citation,
        ),
        ToolDefinition(
            name="get_paper_download_url",
            description="Create a temporary download URL for one paper PDF.",
            input_model=DocumentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_paper_download_url,
        ),
        ToolDefinition(
            name="list_projects",
            description="List Projects accessible to the current user.",
            input_model=ListProjectsInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_list_projects,
        ),
        ToolDefinition(
            name="get_project",
            description="Get one accessible Project.",
            input_model=ProjectInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_project,
        ),
        ToolDefinition(
            name="create_project",
            description="Create a Project owned by the current user.",
            input_model=ProjectCreateRequest,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_create_project,
        ),
        ToolDefinition(
            name="update_project",
            description="Update the title or description of a Project.",
            input_model=UpdateProjectInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_update_project,
        ),
        ToolDefinition(
            name="delete_project",
            description=(
                "Permanently delete a Project when the user explicitly requests it."
            ),
            input_model=ProjectInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.DELETE,
            handler=_delete_project,
        ),
        ToolDefinition(
            name="list_project_papers",
            description="List papers contained in one accessible Project.",
            input_model=ProjectInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_list_project_papers,
        ),
        ToolDefinition(
            name="add_papers_to_project",
            description="Add existing accessible papers to a Project.",
            input_model=AddPapersToProjectInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_add_papers_to_project,
        ),
        ToolDefinition(
            name="remove_paper_from_project",
            description="Remove a paper association from a Project.",
            input_model=ProjectPaperInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.DELETE,
            handler=_remove_paper_from_project,
        ),
        ToolDefinition(
            name="list_paper_projects",
            description="List accessible Projects containing a paper.",
            input_model=DocumentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_list_paper_projects,
        ),
        ToolDefinition(
            name="list_library_papers",
            description=(
                "List papers explicitly saved in the current user's personal Library."
            ),
            input_model=EmptyInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_list_library_papers,
        ),
        ToolDefinition(
            name="get_library_paper",
            description="Get one personal Library entry and its metadata overrides.",
            input_model=DocumentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_library_paper,
        ),
        ToolDefinition(
            name="update_library_paper",
            description="Update a personal Library paper's status or metadata overrides.",
            input_model=UpdateLibraryPaperInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_update_library_paper,
        ),
        ToolDefinition(
            name="remove_library_paper",
            description=(
                "Remove a paper from the personal Library without deleting the document."
            ),
            input_model=DocumentInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.DELETE,
            handler=_remove_library_paper,
        ),
        ToolDefinition(
            name="collect_project_paper_to_library",
            description="Save an accessible Project paper into the personal Library.",
            input_model=CollectProjectPaperInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_collect_project_paper_to_library,
        ),
        ToolDefinition(
            name="ingest_paper_from_url",
            description="Start ingesting a PDF from an HTTP or HTTPS URL.",
            input_model=IngestPaperFromUrlInput,
            execution=ToolExecutionKind.WORKFLOW,
            required_permission=WorkspacePermission.WRITE,
            workflow_handler=ingest_paper_from_url,
        ),
        ToolDefinition(
            name="list_highlights",
            description="List highlights and annotation comments for one paper.",
            input_model=DocumentInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_list_highlights,
        ),
        ToolDefinition(
            name="create_highlight",
            description="Create a highlight on one paper.",
            input_model=CreateHighlightInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_create_highlight,
        ),
        ToolDefinition(
            name="update_highlight",
            description="Update an existing highlight.",
            input_model=UpdateHighlightInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_update_highlight,
        ),
        ToolDefinition(
            name="delete_highlight",
            description="Delete a highlight when the user explicitly requests it.",
            input_model=DeleteHighlightInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.DELETE,
            handler=_delete_highlight,
        ),
        ToolDefinition(
            name="create_annotation_comment",
            description="Add an annotation comment to a highlight.",
            input_model=CreateAnnotationCommentInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_create_annotation_comment,
        ),
        ToolDefinition(
            name="update_annotation_comment",
            description="Update an annotation comment.",
            input_model=UpdateAnnotationCommentInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.WRITE,
            handler=_update_annotation_comment,
        ),
        ToolDefinition(
            name="delete_annotation_comment",
            description=(
                "Delete an annotation comment when the user explicitly requests it."
            ),
            input_model=AnnotationInput,
            execution=ToolExecutionKind.COMMAND,
            required_permission=WorkspacePermission.DELETE,
            handler=_delete_annotation_comment,
        ),
        ToolDefinition(
            name="list_jobs",
            description="List the current user's background processing jobs.",
            input_model=ListJobsInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_list_jobs,
        ),
        ToolDefinition(
            name="get_job",
            description="Get one background processing job.",
            input_model=JobInput,
            execution=ToolExecutionKind.QUERY,
            required_permission=WorkspacePermission.READ,
            handler=_get_job,
        ),
        ToolDefinition(
            name="finish_tool_use",
            description="Finish tool use when no further operation is needed.",
            input_model=EmptyInput,
            execution=ToolExecutionKind.CONTROL,
            required_permission=None,
        ),
    ]
    workspace_names = frozenset(
        definition.name
        for definition in definitions
        if definition.execution is not ToolExecutionKind.CONTROL
    )
    return ToolCatalog(
        definitions,
        [
            ToolProfile(
                name=CONVERSATION_TOOL_PROFILE,
                tool_names=workspace_names | {"finish_tool_use"},
            ),
            ToolProfile(
                name=MCP_TOOL_PROFILE,
                tool_names=workspace_names,
            ),
        ],
    )
