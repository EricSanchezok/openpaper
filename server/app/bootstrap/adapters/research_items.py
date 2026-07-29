"""SQLAlchemy adapter for typed Research items."""

from __future__ import annotations

from uuid import UUID

from app.modules.research.application.contracts import (
    AnnotationCommentResponse,
    CreateAnnotationCommentRequest,
    CreateHighlightThreadRequest,
    ResearchItemResponse,
    ResearchVisibilityRequest,
    UpdateAnnotationCommentRequest,
    UpdateHighlightThreadRequest,
)
from app.bootstrap.adapters.research_repository import (
    HighlightThreadCreate,
    research_repository,
)
from app.shared.domain.enums import ResearchItemKind
from sqlalchemy.orm import Session


class SqlAlchemyResearchItemGateway:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _serialize(self, *, item: object, user_id: int) -> ResearchItemResponse:
        from app.modules.research.infrastructure.models import ResearchItem

        if not isinstance(item, ResearchItem):
            raise TypeError("expected ResearchItem")
        return research_repository.serialize(self._db, item=item, user_id=user_id)

    def list_document(
        self,
        *,
        user_id: int,
        document_id: UUID,
        highlights_only: bool,
    ) -> list[ResearchItemResponse]:
        return [
            self._serialize(item=item, user_id=user_id)
            for item in research_repository.list_for_document(
                self._db,
                document_id=document_id,
                user_id=user_id,
                kind=(ResearchItemKind.HIGHLIGHT_THREAD if highlights_only else None),
            )
        ]

    def list_project(
        self,
        *,
        user_id: int,
        project_id: UUID,
    ) -> list[ResearchItemResponse]:
        return [
            self._serialize(item=item, user_id=user_id)
            for item in research_repository.list_for_project(
                self._db,
                project_id=project_id,
                user_id=user_id,
            )
        ]

    def create_highlight(
        self,
        *,
        user_id: int,
        document_id: UUID,
        request: CreateHighlightThreadRequest,
    ) -> ResearchItemResponse:
        item = research_repository.create_highlight_thread(
            self._db,
            document_id=document_id,
            user_id=user_id,
            create=HighlightThreadCreate(
                quote_text=request.quote_text,
                page_number=request.page_number,
                start_offset=request.start_offset,
                end_offset=request.end_offset,
                position=request.position,
                color=request.color,
                is_shared=request.shared,
            ),
        )
        return self._serialize(item=item, user_id=user_id)

    def update_highlight(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: UpdateHighlightThreadRequest,
    ) -> ResearchItemResponse:
        item = research_repository.update_highlight_thread(
            self._db,
            thread_id=thread_id,
            user_id=user_id,
            values=request.model_dump(exclude_unset=True),
        )
        return self._serialize(item=item, user_id=user_id)

    def delete_item(
        self,
        *,
        user_id: int,
        item_id: UUID,
        confirm_delete_replies: bool,
    ) -> None:
        research_repository.delete_item(
            self._db,
            item_id=item_id,
            user_id=user_id,
            confirm_delete_replies=confirm_delete_replies,
        )

    @staticmethod
    def _comment(
        *,
        comment: object,
        user_id: int,
    ) -> AnnotationCommentResponse:
        from app.modules.research.infrastructure.models import AnnotationComment

        if not isinstance(comment, AnnotationComment):
            raise TypeError("expected AnnotationComment")
        return research_repository.serialize_comment(
            comment,
            user_id=user_id,
            has_scope_access=True,
        )

    def create_comment(
        self,
        *,
        user_id: int,
        thread_id: UUID,
        request: CreateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse:
        return self._comment(
            comment=research_repository.add_comment(
                self._db,
                thread_id=thread_id,
                user_id=user_id,
                content=request.content,
            ),
            user_id=user_id,
        )

    def update_comment(
        self,
        *,
        user_id: int,
        comment_id: UUID,
        request: UpdateAnnotationCommentRequest,
    ) -> AnnotationCommentResponse:
        return self._comment(
            comment=research_repository.update_comment(
                self._db,
                comment_id=comment_id,
                user_id=user_id,
                content=request.content,
            ),
            user_id=user_id,
        )

    def delete_comment(self, *, user_id: int, comment_id: UUID) -> None:
        research_repository.delete_comment(
            self._db,
            comment_id=comment_id,
            user_id=user_id,
        )

    def set_visibility(
        self,
        *,
        user_id: int,
        item_id: UUID,
        request: ResearchVisibilityRequest,
    ) -> ResearchItemResponse:
        item = research_repository.set_visibility(
            self._db,
            item_id=item_id,
            user_id=user_id,
            shared=request.shared,
        )
        return self._serialize(item=item, user_id=user_id)
