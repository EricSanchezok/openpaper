"""Canonical Scholens research-workspace tools.

Names, schemas, descriptions, handlers, and profile membership live here once.
Agent and MCP transports only render or dispatch this catalog.
"""

from __future__ import annotations

import hashlib
from typing import cast
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.workflows.paper_ingestion import PaperIngestionWorkflow
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
from app.shared.domain import JsonValue
from app.shared.domain.enums import JobOperation, PaperStatus
from app.tooling.catalog import ToolCatalog, ToolProfile
from app.tooling.contracts import (
    ToolCallContext,
    ToolDefinition,
    ToolExecutionKind,
    ToolOutcome,
)
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter

CONVERSATION_TOOL_PROFILE = "conversation"
MCP_TOOL_PROFILE = "mcp"
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def _json(value: object) -> JsonValue:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return _JSON_VALUE.validate_python(value)


def _require_paper(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
    query: str = Field(min_length=1, max_length=2_000)


class SearchPaperContentInput(DocumentInput):
    query: str = Field(min_length=1, max_length=2_000)


class PaperContentRangeInput(DocumentInput):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


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
    context: ToolCallContext,
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
    evidence: dict[str, list[str]] = {}
    for item in response.items:
        snippets = [
            f"{snippet.start_line or 1}: {snippet.text}" for snippet in item.snippets
        ]
        if snippets:
            evidence[str(item.document_id)] = snippets
    return ToolOutcome(payload=_json(response), evidence=evidence)


def _get_paper(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
    context: ToolCallContext,
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
    context: ToolCallContext,
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
        evidence=({str(parsed.document_id): [abstract]} if abstract else {}),
    )


def _get_paper_content(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
        evidence=({str(parsed.document_id): [content]} if content else {}),
    )


def _search_paper_content(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
        evidence={str(parsed.document_id): matches},
    )


def _get_paper_content_range(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = PaperContentRangeInput.model_validate(arguments)
    if parsed.end_line < parsed.start_line:
        raise ValueError("end_line must not precede start_line")
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
            raise ValueError("end_line exceeds paper content")
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
        evidence={str(parsed.document_id): lines},
    )


def _get_paper_citation(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = PaperCitationInput.model_validate(arguments)
    _require_paper(capabilities, context, parsed.document_id)
    citation = capabilities.citations(
        actor=context.actor,
        document_id=parsed.document_id,
        style=parsed.style,
    )
    payload = cast(dict[str, JsonValue], _json(citation))
    return ToolOutcome(payload=payload, artifacts=[payload])


def _get_paper_download_url(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
    context: ToolCallContext,
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
    context: ToolCallContext,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    request = ProjectCreateRequest.model_validate(arguments.model_dump())
    result = capabilities.projects.create(actor=context.actor, request=request)
    payload = _json(result)
    return ToolOutcome(
        payload=payload,
        action={"kind": "project_created", "project": payload},
    )


def _update_project(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateProjectInput.model_validate(arguments)
    result = capabilities.projects.update(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ProjectInput.model_validate(arguments)
    capabilities.projects.delete(actor=context.actor, project_id=parsed.project_id)
    payload: dict[str, JsonValue] = {
        "deleted": True,
        "project_id": str(parsed.project_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _list_project_papers(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = AddPapersToProjectInput.model_validate(arguments)
    result = capabilities.projects.add_documents(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = ProjectPaperInput.model_validate(arguments)
    capabilities.projects.remove_document(
        actor=context.actor,
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
    context: ToolCallContext,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    del arguments
    return ToolOutcome(
        payload=_json(capabilities.paper_library.list(actor=context.actor))
    )


def _get_library_paper(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateLibraryPaperInput.model_validate(arguments)
    result = capabilities.paper_library.update(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DocumentInput.model_validate(arguments)
    capabilities.paper_library.remove(
        actor=context.actor,
        document_id=parsed.document_id,
    )
    payload: dict[str, JsonValue] = {
        "removed": True,
        "document_id": str(parsed.document_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _collect_project_paper_to_library(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = CollectProjectPaperInput.model_validate(arguments)
    result = capabilities.projects.collect_document(
        actor=context.actor,
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
    context: ToolCallContext,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = CreateHighlightInput.model_validate(arguments)
    _require_paper(capabilities, context, parsed.document_id)
    request = CreateHighlightThreadRequest.model_validate(
        parsed.model_dump(exclude={"document_id"})
    )
    result = capabilities.research_items.create_highlight(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateHighlightInput.model_validate(arguments)
    result = capabilities.research_items.update_highlight(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = DeleteHighlightInput.model_validate(arguments)
    capabilities.research_items.delete_highlight(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = CreateAnnotationCommentInput.model_validate(arguments)
    result = capabilities.research_items.create_comment(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = UpdateAnnotationCommentInput.model_validate(arguments)
    result = capabilities.research_items.update_comment(
        actor=context.actor,
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
    context: ToolCallContext,
    arguments: BaseModel,
) -> ToolOutcome:
    parsed = AnnotationInput.model_validate(arguments)
    capabilities.research_items.delete_comment(
        actor=context.actor,
        comment_id=parsed.annotation_id,
    )
    payload: dict[str, JsonValue] = {
        "deleted": True,
        "annotation_id": str(parsed.annotation_id),
    }
    return ToolOutcome(payload=payload, action=payload)


def _list_jobs(
    capabilities: ApplicationCapabilities,
    context: ToolCallContext,
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
    context: ToolCallContext,
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
) -> ToolCatalog[ApplicationCapabilities]:
    async def ingest_paper_from_url(
        context: ToolCallContext,
        arguments: BaseModel,
        invocation_key: str,
    ) -> ToolOutcome:
        parsed = IngestPaperFromUrlInput.model_validate(arguments)
        idempotency_key = "tool:" + hashlib.sha256(invocation_key.encode()).hexdigest()
        result: UploadAcceptedResponse = await ingestion.from_url(
            actor=context.actor,
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

    query = ToolExecutionKind.QUERY
    command = ToolExecutionKind.COMMAND
    definitions = [
        ToolDefinition(
            "search_papers",
            "Search the active conversation paper collection.",
            SearchPapersInput,
            query,
            _search_papers,
        ),
        ToolDefinition(
            "get_paper",
            "Get canonical metadata for one paper in the active context.",
            DocumentInput,
            query,
            _get_paper,
        ),
        ToolDefinition(
            "get_paper_abstract",
            "Get the abstract of one paper in the active context.",
            DocumentInput,
            query,
            _get_paper_abstract,
        ),
        ToolDefinition(
            "get_paper_content",
            "Read the complete extracted text of one paper.",
            DocumentInput,
            query,
            _get_paper_content,
        ),
        ToolDefinition(
            "search_paper_content",
            "Search one paper's extracted text with a regular expression.",
            SearchPaperContentInput,
            query,
            _search_paper_content,
        ),
        ToolDefinition(
            "get_paper_content_range",
            "Read an inclusive one-based line range from one paper.",
            PaperContentRangeInput,
            query,
            _get_paper_content_range,
        ),
        ToolDefinition(
            "get_paper_citation",
            "Resolve and format bibliographic metadata for one paper.",
            PaperCitationInput,
            query,
            _get_paper_citation,
        ),
        ToolDefinition(
            "get_paper_download_url",
            "Create a temporary download URL for one paper PDF.",
            DocumentInput,
            query,
            _get_paper_download_url,
        ),
        ToolDefinition(
            "list_projects",
            "List Projects accessible to the current user.",
            ListProjectsInput,
            query,
            _list_projects,
        ),
        ToolDefinition(
            "get_project",
            "Get one accessible Project.",
            ProjectInput,
            query,
            _get_project,
        ),
        ToolDefinition(
            "create_project",
            "Create a Project owned by the current user.",
            ProjectCreateRequest,
            command,
            _create_project,
        ),
        ToolDefinition(
            "update_project",
            "Update the title or description of a Project.",
            UpdateProjectInput,
            command,
            _update_project,
        ),
        ToolDefinition(
            "delete_project",
            "Permanently delete a Project when the user explicitly requests it.",
            ProjectInput,
            command,
            _delete_project,
        ),
        ToolDefinition(
            "list_project_papers",
            "List papers contained in one accessible Project.",
            ProjectInput,
            query,
            _list_project_papers,
        ),
        ToolDefinition(
            "add_papers_to_project",
            "Add existing accessible papers to a Project.",
            AddPapersToProjectInput,
            command,
            _add_papers_to_project,
        ),
        ToolDefinition(
            "remove_paper_from_project",
            "Remove a paper association from a Project.",
            ProjectPaperInput,
            command,
            _remove_paper_from_project,
        ),
        ToolDefinition(
            "list_paper_projects",
            "List accessible Projects containing a paper.",
            DocumentInput,
            query,
            _list_paper_projects,
        ),
        ToolDefinition(
            "list_library_papers",
            "List papers explicitly saved in the current user's personal Library.",
            EmptyInput,
            query,
            _list_library_papers,
        ),
        ToolDefinition(
            "get_library_paper",
            "Get one personal Library entry and its metadata overrides.",
            DocumentInput,
            query,
            _get_library_paper,
        ),
        ToolDefinition(
            "update_library_paper",
            "Update a personal Library paper's status or metadata overrides.",
            UpdateLibraryPaperInput,
            command,
            _update_library_paper,
        ),
        ToolDefinition(
            "remove_library_paper",
            "Remove a paper from the personal Library without deleting the document.",
            DocumentInput,
            command,
            _remove_library_paper,
        ),
        ToolDefinition(
            "collect_project_paper_to_library",
            "Save an accessible Project paper into the personal Library.",
            CollectProjectPaperInput,
            command,
            _collect_project_paper_to_library,
        ),
        ToolDefinition(
            "ingest_paper_from_url",
            "Start ingesting a PDF from an HTTP or HTTPS URL.",
            IngestPaperFromUrlInput,
            ToolExecutionKind.WORKFLOW,
            workflow_handler=ingest_paper_from_url,
        ),
        ToolDefinition(
            "list_highlights",
            "List highlights and annotation comments for one paper.",
            DocumentInput,
            query,
            _list_highlights,
        ),
        ToolDefinition(
            "create_highlight",
            "Create a highlight on one paper.",
            CreateHighlightInput,
            command,
            _create_highlight,
        ),
        ToolDefinition(
            "update_highlight",
            "Update an existing highlight.",
            UpdateHighlightInput,
            command,
            _update_highlight,
        ),
        ToolDefinition(
            "delete_highlight",
            "Delete a highlight when the user explicitly requests it.",
            DeleteHighlightInput,
            command,
            _delete_highlight,
        ),
        ToolDefinition(
            "create_annotation_comment",
            "Add an annotation comment to a highlight.",
            CreateAnnotationCommentInput,
            command,
            _create_annotation_comment,
        ),
        ToolDefinition(
            "update_annotation_comment",
            "Update an annotation comment.",
            UpdateAnnotationCommentInput,
            command,
            _update_annotation_comment,
        ),
        ToolDefinition(
            "delete_annotation_comment",
            "Delete an annotation comment when the user explicitly requests it.",
            AnnotationInput,
            command,
            _delete_annotation_comment,
        ),
        ToolDefinition(
            "list_jobs",
            "List the current user's background processing jobs.",
            ListJobsInput,
            query,
            _list_jobs,
        ),
        ToolDefinition(
            "get_job",
            "Get one background processing job.",
            JobInput,
            query,
            _get_job,
        ),
        ToolDefinition(
            "finish_tool_use",
            "Finish tool use when no further operation is needed.",
            EmptyInput,
            ToolExecutionKind.CONTROL,
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
