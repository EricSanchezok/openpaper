"""Research-item commands and queries independent of HTTP and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
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
from app.shared.application import Actor, OperationContext
from app.shared.domain.enums import RoleType

RESEARCH_HIGHLIGHT_CREATED = OperationAction("research.highlight_created")
RESEARCH_HIGHLIGHT_UPDATED = OperationAction("research.highlight_updated")
RESEARCH_HIGHLIGHT_DELETED = OperationAction("research.highlight_deleted")
RESEARCH_ANNOTATION_COMMENT_CREATED = OperationAction(
    "research.annotation_comment_created"
)
RESEARCH_ANNOTATION_COMMENT_UPDATED = OperationAction(
    "research.annotation_comment_updated"
)
RESEARCH_ANNOTATION_COMMENT_DELETED = OperationAction(
    "research.annotation_comment_deleted"
)
RESEARCH_VISIBILITY_UPDATED = OperationAction("research.visibility_updated")
RESEARCH_ITEM_DELETED = OperationAction("research.item_deleted")


@dataclass(frozen=True, slots=True)
class ResearchItemChange[T]:
    value: T
    changed: bool


class ResearchItemGateway(Protocol):
    def list_document(
        self,
        *,
        user_id: int,
        document_id: UUID,
        highlights_only: bool,
    ) -> list[ResearchItemResponse]: ...

    def list_project(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ResearchItemResponse]: ...

    def create_highlight(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: CreateHighlightThreadRequest,
        content_role: RoleType,
    ) -> ResearchItemResponse: ...

    def update_highlight(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: UpdateHighlightThreadRequest,
    ) -> ResearchItemChange[ResearchItemResponse]: ...

    def delete_item(
        self,
        *,
        user_id: int,
        item_id: UUID,
        confirm_delete_replies: bool,
        origin_operation_id: UUID,
        correlation_id: UUID,
    ) -> None: ...

    def create_comment(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
        content_role: RoleType,
    ) -> AnnotationCommentResponse: ...

    def update_comment(
        self,
        *,
        user_id: int,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> ResearchItemChange[AnnotationCommentResponse]: ...

    def delete_comment(self, *, user_id: int, comment_id: UUID) -> None: ...

    def set_visibility(
        self,
        *,
        user_id: int,
        item_id: UUID,
        request: ResearchVisibilityRequest,
    ) -> ResearchItemChange[ResearchItemResponse]: ...


class ResearchItems:
    def __init__(
        self,
        gateway: ResearchItemGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def list_document(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        highlights_only: bool = False,
    ) -> ResearchItemListResponse:
        return ResearchItemListResponse(
            items=self._gateway.list_document(
                user_id=actor.id,
                document_id=document_id,
                highlights_only=highlights_only,
            )
        )

    def list_project(
        self,
        *,
        actor: Actor,
        project_id: UUID,
    ) -> ResearchItemListResponse:
        return ResearchItemListResponse(
            items=self._gateway.list_project(
                user_id=actor.id,
                project_id=project_id,
            )
        )

    def create_highlight(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: CreateHighlightThreadRequest,
        content_role: RoleType,
    ) -> ResearchItemResponse:
        if not isinstance(content_role, RoleType):
            raise TypeError("content_role must be a RoleType")
        result = self._gateway.create_highlight(
            user_id=actor.id,
            document_id=document_id,
            request=request,
            content_role=content_role,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_HIGHLIGHT_CREATED,
            resources=(ResourceRef("research_item", str(result.id)),),
        )
        return result

    def update_highlight(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        thread_id: UUID,
        request: UpdateHighlightThreadRequest,
    ) -> ResearchItemResponse:
        result = self._gateway.update_highlight(
            user_id=actor.id,
            thread_id=thread_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=RESEARCH_HIGHLIGHT_UPDATED,
                resources=(ResourceRef("research_item", str(thread_id)),),
            )
        return result.value

    def delete_highlight(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        thread_id: UUID,
        request: DeleteHighlightThreadRequest,
    ) -> DeleteResearchItemResponse:
        self._gateway.delete_item(
            user_id=actor.id,
            item_id=thread_id,
            confirm_delete_replies=request.confirm_delete_replies,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_HIGHLIGHT_DELETED,
            resources=(ResourceRef("research_item", str(thread_id)),),
        )
        return DeleteResearchItemResponse()

    def create_comment(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
        content_role: RoleType,
    ) -> AnnotationCommentResponse:
        if not isinstance(content_role, RoleType):
            raise TypeError("content_role must be a RoleType")
        result = self._gateway.create_comment(
            user_id=actor.id,
            thread_id=thread_id,
            request=request,
            content_role=content_role,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ANNOTATION_COMMENT_CREATED,
            resources=(ResourceRef("annotation_comment", str(result.id)),),
        )
        return result

    def update_comment(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse:
        result = self._gateway.update_comment(
            user_id=actor.id,
            comment_id=comment_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=RESEARCH_ANNOTATION_COMMENT_UPDATED,
                resources=(ResourceRef("annotation_comment", str(comment_id)),),
            )
        return result.value

    def delete_comment(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        comment_id: UUID,
    ) -> None:
        self._gateway.delete_comment(user_id=actor.id, comment_id=comment_id)
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ANNOTATION_COMMENT_DELETED,
            resources=(ResourceRef("annotation_comment", str(comment_id)),),
        )

    def set_visibility(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item_id: UUID,
        request: ResearchVisibilityRequest,
    ) -> ResearchItemResponse:
        result = self._gateway.set_visibility(
            user_id=actor.id,
            item_id=item_id,
            request=request,
        )
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=RESEARCH_VISIBILITY_UPDATED,
                resources=(ResourceRef("research_item", str(item_id)),),
            )
        return result.value

    def delete_item(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        item_id: UUID,
    ) -> DeleteResearchItemResponse:
        self._gateway.delete_item(
            user_id=actor.id,
            item_id=item_id,
            confirm_delete_replies=False,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
        self._journal.append(
            actor=actor,
            operation=operation,
            action=RESEARCH_ITEM_DELETED,
            resources=(ResourceRef("research_item", str(item_id)),),
        )
        return DeleteResearchItemResponse()
