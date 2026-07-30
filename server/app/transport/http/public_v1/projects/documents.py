"""HTTP adapter for documents held by Projects."""

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectListResponse,
    ProjectPaperCollectedResponse,
    ProjectPaperFileUrlResponse,
    ProjectPaperListResponse,
    ProjectPapersAddedResponse,
    ProjectPendingUploadsResponse,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Response, status

project_papers_router = APIRouter()
paper_projects_router = APIRouter()
library_project_papers_router = APIRouter()


@library_project_papers_router.post(
    "/papers",
    response_model=ProjectPaperCollectedResponse,
    status_code=status.HTTP_201_CREATED,
)
def collect_paper_from_project(
    request: CollectPaperFromProjectRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectPaperCollectedResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.collect_document(
            actor=current_user,
            operation=operation,
            request=request,
        )
    )


@project_papers_router.post(
    "/{project_id}/papers",
    response_model=ProjectPapersAddedResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_paper_to_project(
    project_id: UUID,
    request: AddPaperToProjectRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectPapersAddedResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.add_documents(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            request=request,
        )
    )


@project_papers_router.get(
    "/{project_id}/papers",
    response_model=ProjectPaperListResponse,
)
def get_project_papers(
    project_id: UUID,
    load_urls: bool = False,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPaperListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.documents(
            actor=current_user,
            project_id=project_id,
            load_urls=load_urls,
        )
    )


@project_papers_router.get(
    "/{project_id}/papers/pending-jobs",
    response_model=ProjectPendingUploadsResponse,
)
def get_project_pending_jobs(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPendingUploadsResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.pending_uploads(
            actor=current_user,
            project_id=project_id,
        )
    )


@project_papers_router.get(
    "/{project_id}/papers/{document_id}/download-url",
    response_model=ProjectPaperFileUrlResponse,
)
def get_project_paper_file_url(
    project_id: UUID,
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPaperFileUrlResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.document_download(
            actor=current_user,
            project_id=project_id,
            document_id=document_id,
        )
    )


@paper_projects_router.get(
    "/{document_id}/projects",
    response_model=ProjectListResponse,
)
def get_projects_from_document_id(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.projects_for_document(
            actor=current_user,
            document_id=document_id,
        )
    )


@project_papers_router.delete(
    "/{project_id}/papers/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_paper_from_project(
    project_id: UUID,
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.projects.remove_document(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            document_id=document_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
