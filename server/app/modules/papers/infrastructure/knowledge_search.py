"""Library search over canonical documents and visible research threads."""

from uuid import UUID

from app.database.models import (
    AnnotationComment,
    Document,
    HighlightThread,
    LibraryPaper,
    ResearchItem,
    ResearchItemKind,
    ResearchScopeType,
)
from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.search import (
    AnnotationSearchResult,
    HighlightSearchResult,
    PaperSearchRequest,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSearchStats,
)
from app.shared.application import Actor
from app.modules.projects.infrastructure.models import (
    Project,
    ProjectCollaborator,
    ProjectPaper,
)
from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session


def _visible_research(user_id: int) -> ColumnElement[bool]:
    return or_(
        ResearchItem.is_shared.is_(True),
        ResearchItem.created_by_id == user_id,
    )


def _accessible_project_documents(user_id: int) -> Select[tuple[UUID]]:
    return (
        select(ProjectPaper.document_id)
        .join(Project, Project.id == ProjectPaper.project_id)
        .outerjoin(
            ProjectCollaborator,
            and_(
                ProjectCollaborator.project_id == Project.id,
                ProjectCollaborator.user_id == user_id,
            ),
        )
        .where(
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            )
        )
    )


def search_knowledge_base(
    db: Session,
    user: Actor,
    query: str,
    limit: int = 50,
    offset: int = 0,
) -> PaperSearchResponse:
    search_pattern = f"%{query.lower()}%"
    text_query = func.websearch_to_tsquery("pg_catalog.english", query)
    matching_highlight_documents = (
        select(ResearchItem.document_id)
        .join(
            HighlightThread,
            HighlightThread.research_item_id == ResearchItem.id,
        )
        .where(
            ResearchItem.scope_type == ResearchScopeType.DOCUMENT.value,
            _visible_research(user.id),
            func.lower(HighlightThread.quote_text).like(search_pattern),
        )
    )
    matching_comment_documents = (
        select(ResearchItem.document_id)
        .join(
            AnnotationComment,
            AnnotationComment.thread_id == ResearchItem.id,
        )
        .where(
            ResearchItem.scope_type == ResearchScopeType.DOCUMENT.value,
            _visible_research(user.id),
            func.lower(AnnotationComment.content).like(search_pattern),
        )
    )
    paper_statement = (
        select(Document)
        .outerjoin(
            LibraryPaper,
            and_(
                LibraryPaper.document_id == Document.id,
                LibraryPaper.user_id == user.id,
            ),
        )
        .where(
            or_(
                LibraryPaper.user_id == user.id,
                Document.id.in_(_accessible_project_documents(user.id)),
            ),
            or_(
                Document.ts_vector.op("@@")(text_query),
                Document.id.in_(matching_highlight_documents),
                Document.id.in_(matching_comment_documents),
            ),
        )
        .order_by(
            func.ts_rank_cd(Document.ts_vector, text_query).desc(),
            LibraryPaper.last_accessed_at.desc().nullslast(),
            Document.id,
        )
    )
    total_papers = int(
        db.scalar(
            select(func.count()).select_from(paper_statement.order_by(None).subquery())
        )
        or 0
    )
    papers = list(db.scalars(paper_statement.offset(offset).limit(limit)).all())
    document_ids = [paper.id for paper in papers]
    library_by_document = {
        entry.document_id: entry
        for entry in db.scalars(
            select(LibraryPaper).where(
                LibraryPaper.user_id == user.id,
                LibraryPaper.document_id.in_(document_ids),
            )
        ).all()
    }

    highlight_rows = (
        db.execute(
            select(ResearchItem, HighlightThread)
            .join(
                HighlightThread,
                HighlightThread.research_item_id == ResearchItem.id,
            )
            .where(
                ResearchItem.document_id.in_(document_ids),
                _visible_research(user.id),
                func.lower(HighlightThread.quote_text).like(search_pattern),
            )
            .order_by(ResearchItem.created_at.desc())
        ).all()
        if document_ids
        else []
    )
    comment_rows = (
        db.execute(
            select(ResearchItem, HighlightThread, AnnotationComment)
            .join(
                HighlightThread,
                HighlightThread.research_item_id == ResearchItem.id,
            )
            .join(
                AnnotationComment,
                AnnotationComment.thread_id == ResearchItem.id,
            )
            .where(
                ResearchItem.document_id.in_(document_ids),
                _visible_research(user.id),
                func.lower(AnnotationComment.content).like(search_pattern),
            )
            .order_by(AnnotationComment.created_at.desc())
        ).all()
        if document_ids
        else []
    )

    highlights_by_document: dict[
        object, list[tuple[ResearchItem, HighlightThread]]
    ] = {}
    for item, thread in highlight_rows:
        highlights_by_document.setdefault(item.document_id, []).append((item, thread))
    comments_by_document: dict[
        object,
        list[tuple[ResearchItem, HighlightThread, AnnotationComment]],
    ] = {}
    for item, thread, comment in comment_rows:
        comments_by_document.setdefault(item.document_id, []).append(
            (item, thread, comment)
        )

    results: list[PaperSearchResult] = []
    total_highlights = 0
    total_annotations = 0
    for paper in papers:
        highlight_results = [
            HighlightSearchResult(
                id=str(item.id),
                raw_text=thread.quote_text,
                start_offset=thread.start_offset,
                end_offset=thread.end_offset,
                page_number=thread.page_number,
                role=thread.role,
                created_at=item.created_at,
            )
            for item, thread in highlights_by_document.get(paper.id, [])
        ]
        annotation_results = [
            AnnotationSearchResult(
                id=str(comment.id),
                content=comment.content,
                role=comment.role,
                created_at=comment.created_at,
                highlight=HighlightSearchResult(
                    id=str(item.id),
                    raw_text=thread.quote_text,
                    start_offset=thread.start_offset,
                    end_offset=thread.end_offset,
                    page_number=thread.page_number,
                    role=thread.role,
                    created_at=item.created_at,
                ),
            )
            for item, thread, comment in comments_by_document.get(paper.id, [])
        ]
        library_paper = library_by_document.get(paper.id)
        results.append(
            PaperSearchResult(
                document_id=paper.id,
                title=paper.title,
                authors=paper.authors,
                abstract=paper.abstract,
                status=library_paper.status if library_paper else paper.processing_status,
                publish_date=paper.publish_date,
                created_at=paper.created_at,
                last_accessed_at=(
                    library_paper.last_accessed_at
                    if library_paper
                    else paper.created_at
                ),
                highlights=highlight_results,
                annotations=annotation_results,
                preview_url=(
                    s3_service.generate_presigned_url(paper.preview_s3_key)
                    if paper.preview_s3_key
                    else None
                ),
            )
        )
        total_highlights += len(highlight_results)
        total_annotations += len(annotation_results)

    return PaperSearchResponse(
        papers=results,
        total_papers=total_papers,
        total_highlights=total_highlights,
        total_annotations=total_annotations,
    )


class PostgresPaperSearch:
    """PostgreSQL implementation; callers depend only on PaperSearchPort."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchRequest,
    ) -> PaperSearchResponse:
        return search_knowledge_base(
            self._db,
            user=actor,
            query=request.query,
            limit=request.limit,
            offset=request.offset,
        )

    def stats(self, *, actor: Actor) -> PaperSearchStats:
        total_papers = int(
            self._db.scalar(
                select(func.count(Document.id)).where(
                    or_(
                        Document.id.in_(
                            select(LibraryPaper.document_id).where(
                                LibraryPaper.user_id == actor.id
                            )
                        ),
                        Document.id.in_(_accessible_project_documents(actor.id)),
                    )
                )
            )
            or 0
        )
        total_highlights = int(
            self._db.scalar(
                select(func.count(ResearchItem.id)).where(
                    ResearchItem.created_by_id == actor.id,
                    ResearchItem.kind == ResearchItemKind.HIGHLIGHT_THREAD.value,
                )
            )
            or 0
        )
        total_annotations = int(
            self._db.scalar(
                select(func.count(AnnotationComment.id)).where(
                    AnnotationComment.created_by_id == actor.id
                )
            )
            or 0
        )
        return PaperSearchStats(
            total_papers=total_papers,
            total_highlights=total_highlights,
            total_annotations=total_annotations,
            searchable_items=total_papers + total_highlights + total_annotations,
        )
