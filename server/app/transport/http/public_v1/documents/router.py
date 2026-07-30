"""HTTP adapters for Papers, Library entries, and public shares."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor, get_citation_workflow
from app.bootstrap.workflows.citation import CitationWorkflow
from app.modules.papers.application.contracts.citation import CitationResult
from app.modules.papers.application.contracts.documents import (
    CollectPublicPaperResponse,
    DocumentContentResponse,
    DocumentFileUrlResponse,
    DocumentResponse,
    LibraryPaperListResponse,
    LibraryPaperResponse,
    LibraryPaperShareResponse,
    LibraryPaperUpdateRequest,
    PublicPaperResponse,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Response, status

document_router = APIRouter()
library_router = APIRouter()
public_document_router = APIRouter()


@library_router.get("/papers", response_model=LibraryPaperListResponse)
def list_library_papers(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperListResponse:
    return executor.query(
        lambda capabilities: capabilities.paper_library.list(actor=current_user)
    )


@library_router.patch(
    "/papers/{document_id}",
    response_model=LibraryPaperResponse,
)
def update_library_paper(
    document_id: UUID,
    request: LibraryPaperUpdateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> LibraryPaperResponse:
    return executor.command(
        lambda capabilities: capabilities.paper_library.update(
            actor=current_user,
            operation=operation,
            document_id=document_id,
            request=request,
        )
    )


@library_router.get(
    "/papers/{document_id}",
    response_model=LibraryPaperResponse,
)
def get_library_paper_by_document(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> LibraryPaperResponse:
    return executor.query(
        lambda capabilities: capabilities.paper_library.get(
            actor=current_user,
            document_id=document_id,
        )
    )


@library_router.post(
    "/papers/{document_id}/share",
    response_model=LibraryPaperShareResponse,
    status_code=status.HTTP_201_CREATED,
)
def share_library_paper(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> LibraryPaperShareResponse:
    return executor.command(
        lambda capabilities: capabilities.paper_library.share(
            actor=current_user,
            operation=operation,
            document_id=document_id,
        )
    )


@library_router.delete(
    "/papers/{document_id}/share",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unshare_library_paper(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.paper_library.unshare(
            actor=current_user,
            operation=operation,
            document_id=document_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@library_router.delete(
    "/papers/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_library_paper(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.paper_library.remove(
            actor=current_user,
            operation=operation,
            document_id=document_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@document_router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    project_id: UUID | None = None,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> DocumentResponse:
    return executor.query(
        lambda capabilities: capabilities.paper_details(
            actor=current_user,
            document_id=document_id,
            project_id=project_id,
        )
    )


@document_router.get(
    "/{document_id}/content",
    response_model=DocumentContentResponse,
)
def get_document_content(
    document_id: UUID,
    project_id: UUID | None = None,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> DocumentContentResponse:
    paper = executor.query(
        lambda capabilities: capabilities.paper_content.read(
            actor=current_user,
            document_id=document_id,
            project_id=project_id,
        )
    )
    return DocumentContentResponse(
        document_id=paper.document_id,
        title=paper.title,
        abstract=paper.abstract,
        content=paper.raw_content,
    )


@document_router.get(
    "/{document_id}/download-url",
    response_model=DocumentFileUrlResponse,
)
def get_document_file_url(
    document_id: UUID,
    project_id: UUID | None = None,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> DocumentFileUrlResponse:
    return executor.query(
        lambda capabilities: capabilities.paper_download(
            actor=current_user,
            document_id=document_id,
            project_id=project_id,
        )
    )


@document_router.get(
    "/{document_id}/citation",
    response_model=CitationResult,
)
def get_document_citation(
    document_id: UUID,
    style: str = "APA",
    project_id: UUID | None = None,
    workflow: CitationWorkflow = Depends(get_citation_workflow),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> CitationResult:
    return workflow.run(
        actor=current_user,
        operation=operation,
        document_id=document_id,
        style=style,
        project_id=project_id,
    )


@public_document_router.get(
    "/{share_token}",
    response_model=PublicPaperResponse,
)
def get_public_paper(
    share_token: str,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> PublicPaperResponse:
    return executor.query(
        lambda capabilities: capabilities.paper_library.get_public(
            share_token=share_token
        )
    )


@public_document_router.post(
    "/{share_token}/collect",
    response_model=CollectPublicPaperResponse,
    status_code=status.HTTP_201_CREATED,
)
def collect_public_paper(
    share_token: str,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> CollectPublicPaperResponse:
    return executor.command(
        lambda capabilities: capabilities.paper_library.collect_public(
            actor=current_user,
            operation=operation,
            share_token=share_token,
        )
    )
