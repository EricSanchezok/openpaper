"""HTTP adapters for typed, scope-aware Research items."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    CreateAnnotationCommentRequest,
    CreateHighlightThreadRequest,
    DeleteHighlightThreadRequest,
    DeleteResearchItemResponse,
    ResearchItemListResponse,
    ResearchItemResponse,
    ResearchVisibilityRequest,
    UpdateAnnotationCommentRequest,
    UpdateHighlightThreadRequest,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.shared.domain.enums import RoleType
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Response, status

document_research_router = APIRouter()
project_research_router = APIRouter()
research_router = APIRouter()


@document_research_router.get(
    "/{document_id}/research-items",
    response_model=ResearchItemListResponse,
)
def list_document_research_items(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemListResponse:
    return executor.query(
        lambda capabilities: capabilities.research_items.list_document(
            actor=current_user,
            document_id=document_id,
        )
    )


@project_research_router.get(
    "/{project_id}/research-items",
    response_model=ResearchItemListResponse,
)
def list_project_research_items(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemListResponse:
    return executor.query(
        lambda capabilities: capabilities.research_items.list_project(
            actor=current_user,
            project_id=project_id,
        )
    )


@document_research_router.get(
    "/{document_id}/highlight-threads",
    response_model=ResearchItemListResponse,
)
def list_highlight_threads(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ResearchItemListResponse:
    return executor.query(
        lambda capabilities: capabilities.research_items.list_document(
            actor=current_user,
            document_id=document_id,
            highlights_only=True,
        )
    )


@document_research_router.post(
    "/{document_id}/highlight-threads",
    response_model=ResearchItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_highlight_thread(
    document_id: UUID,
    request: CreateHighlightThreadRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ResearchItemResponse:
    return executor.command(
        lambda capabilities: capabilities.research_items.create_highlight(
            actor=current_user,
            operation=operation,
            content_role=RoleType.USER,
            document_id=document_id,
            request=request,
        )
    )


@research_router.patch(
    "/highlight-threads/{thread_id}",
    response_model=ResearchItemResponse,
)
def update_highlight_thread(
    thread_id: UUID,
    request: UpdateHighlightThreadRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ResearchItemResponse:
    return executor.command(
        lambda capabilities: capabilities.research_items.update_highlight(
            actor=current_user,
            operation=operation,
            thread_id=thread_id,
            request=request,
        )
    )


@research_router.delete(
    "/highlight-threads/{thread_id}",
    response_model=DeleteResearchItemResponse,
)
def delete_highlight_thread(
    thread_id: UUID,
    request: DeleteHighlightThreadRequest = Depends(),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> DeleteResearchItemResponse:
    return executor.command(
        lambda capabilities: capabilities.research_items.delete_highlight(
            actor=current_user,
            operation=operation,
            thread_id=thread_id,
            request=request,
        )
    )


@research_router.post(
    "/highlight-threads/{thread_id}/comments",
    response_model=AnnotationCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation_comment(
    thread_id: UUID,
    request: CreateAnnotationCommentRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> AnnotationCommentResponse:
    return executor.command(
        lambda capabilities: capabilities.research_items.create_comment(
            actor=current_user,
            operation=operation,
            content_role=RoleType.USER,
            thread_id=thread_id,
            request=request,
        )
    )


@research_router.patch(
    "/annotation-comments/{comment_id}",
    response_model=AnnotationCommentResponse,
)
def update_annotation_comment(
    comment_id: UUID,
    request: UpdateAnnotationCommentRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> AnnotationCommentResponse:
    return executor.command(
        lambda capabilities: capabilities.research_items.update_comment(
            actor=current_user,
            operation=operation,
            comment_id=comment_id,
            request=request,
        )
    )


@research_router.delete(
    "/annotation-comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_annotation_comment(
    comment_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.research_items.delete_comment(
            actor=current_user,
            operation=operation,
            comment_id=comment_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@research_router.patch(
    "/research-items/{item_id}",
    response_model=ResearchItemResponse,
)
def update_research_item(
    item_id: UUID,
    request: ResearchVisibilityRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ResearchItemResponse:
    return executor.command(
        lambda capabilities: capabilities.research_items.set_visibility(
            actor=current_user,
            operation=operation,
            item_id=item_id,
            request=request,
        )
    )


@research_router.delete(
    "/research-items/{item_id}",
    response_model=DeleteResearchItemResponse,
)
def delete_research_item(
    item_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> DeleteResearchItemResponse:
    return executor.command(
        lambda capabilities: capabilities.research_items.delete_item(
            actor=current_user,
            operation=operation,
            item_id=item_id,
        )
    )
