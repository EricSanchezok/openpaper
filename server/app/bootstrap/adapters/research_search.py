"""SQLAlchemy adapter for highlight and annotation search."""

from __future__ import annotations

from app.modules.research.application.search import (
    ResearchSearchComment,
    ResearchSearchQuery,
    ResearchSearchResponse,
    ResearchSearchResult,
)
from app.bootstrap.adapters.research_access import research_item_visible_to
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    HighlightThread,
    ResearchItem,
)
from app.shared.application import Actor
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session, joinedload


class SqlResearchSearch:
    def __init__(self, db: Session) -> None:
        self._db = db

    def search(
        self,
        *,
        actor: Actor,
        request: ResearchSearchQuery,
    ) -> ResearchSearchResponse:
        pattern = f"%{request.query.casefold()}%"
        matching_comment = exists(
            select(AnnotationComment.id).where(
                AnnotationComment.thread_id == HighlightThread.research_item_id,
                func.lower(AnnotationComment.content).like(pattern),
            )
        )
        statement = (
            select(ResearchItem)
            .join(
                HighlightThread,
                HighlightThread.research_item_id == ResearchItem.id,
            )
            .where(
                research_item_visible_to(actor.id),
                or_(
                    func.lower(HighlightThread.quote_text).like(pattern),
                    matching_comment,
                ),
            )
            .options(
                joinedload(ResearchItem.document),
                joinedload(ResearchItem.highlight_thread).selectinload(
                    HighlightThread.comments
                ),
            )
            .order_by(ResearchItem.created_at.desc(), ResearchItem.id)
        )
        total = int(
            self._db.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = self._db.scalars(
            statement.offset(request.offset).limit(request.limit)
        ).all()
        items: list[ResearchSearchResult] = []
        for item in rows:
            thread = item.highlight_thread
            if thread is None or item.document_id is None:
                continue
            comments = [
                ResearchSearchComment(
                    id=comment.id,
                    content=comment.content,
                    role=comment.role,
                    created_at=comment.created_at,
                )
                for comment in thread.comments
                if request.query.casefold() in comment.content.casefold()
            ]
            items.append(
                ResearchSearchResult(
                    id=item.id,
                    document_id=item.document_id,
                    document_title=item.document.title if item.document else None,
                    quote_text=thread.quote_text,
                    page_number=thread.page_number,
                    start_offset=thread.start_offset,
                    end_offset=thread.end_offset,
                    role=thread.role,
                    created_at=item.created_at,
                    matching_comments=comments,
                )
            )
        return ResearchSearchResponse(items=items, total=total)
