"""Research-item commands and queries independent of HTTP and persistence."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

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
from app.shared.application import Actor


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
    ) -> ResearchItemResponse: ...

    def update_highlight(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: UpdateHighlightThreadRequest,
    ) -> ResearchItemResponse: ...

    def delete_item(
        self,
        *,
        user_id: int,
        item_id: UUID,
        confirm_delete_replies: bool,
    ) -> None: ...

    def create_comment(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse: ...

    def update_comment(
        self,
        *,
        user_id: int,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse: ...

    def delete_comment(self, *, user_id: int, comment_id: UUID) -> None: ...

    def set_visibility(
        self,
        *,
        user_id: int,
        item_id: UUID,
        request: ResearchVisibilityRequest,
    ) -> ResearchItemResponse: ...


class ResearchItems:
    def __init__(self, gateway: ResearchItemGateway) -> None:
        self._gateway = gateway

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
        document_id: UUID,
        request: CreateHighlightThreadRequest,
    ) -> ResearchItemResponse:
        return self._gateway.create_highlight(
            user_id=actor.id,
            document_id=document_id,
            request=request,
        )

    def update_highlight(
        self,
        *,
        actor: Actor,
        thread_id: UUID,
        request: UpdateHighlightThreadRequest,
    ) -> ResearchItemResponse:
        return self._gateway.update_highlight(
            user_id=actor.id,
            thread_id=thread_id,
            request=request,
        )

    def delete_highlight(
        self,
        *,
        actor: Actor,
        thread_id: UUID,
        request: DeleteHighlightThreadRequest,
    ) -> DeleteResearchItemResponse:
        self._gateway.delete_item(
            user_id=actor.id,
            item_id=thread_id,
            confirm_delete_replies=request.confirm_delete_replies,
        )
        return DeleteResearchItemResponse()

    def create_comment(
        self,
        *,
        actor: Actor,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse:
        return self._gateway.create_comment(
            user_id=actor.id,
            thread_id=thread_id,
            request=request,
        )

    def update_comment(
        self,
        *,
        actor: Actor,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse:
        return self._gateway.update_comment(
            user_id=actor.id,
            comment_id=comment_id,
            request=request,
        )

    def delete_comment(self, *, actor: Actor, comment_id: UUID) -> None:
        self._gateway.delete_comment(user_id=actor.id, comment_id=comment_id)

    def set_visibility(
        self,
        *,
        actor: Actor,
        item_id: UUID,
        request: ResearchVisibilityRequest,
    ) -> ResearchItemResponse:
        return self._gateway.set_visibility(
            user_id=actor.id,
            item_id=item_id,
            request=request,
        )

    def delete_item(
        self,
        *,
        actor: Actor,
        item_id: UUID,
    ) -> DeleteResearchItemResponse:
        self._gateway.delete_item(
            user_id=actor.id,
            item_id=item_id,
            confirm_delete_replies=False,
        )
        return DeleteResearchItemResponse()
