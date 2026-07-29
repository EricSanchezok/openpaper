"""PostgreSQL FTS adapter for canonical papers and parsed passages."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from app.helpers.s3 import s3_service
from app.modules.papers.application.contracts.search import (
    PaperSearchQuery,
    PaperSearchResponse,
    PaperSearchResult,
    PaperSearchScope,
    PaperSearchSnippet,
    PaperSearchSort,
    PaperSearchStats,
)
from app.modules.papers.infrastructure.models import (
    Document,
    DocumentPassage,
    LibraryPaper,
)
from app.shared.application import Actor
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session


def _visibility_condition(
    *,
    actor: Actor,
    scope: PaperSearchScope,
    project_document_ids: tuple[UUID, ...],
) -> ColumnElement[bool]:
    in_library = LibraryPaper.user_id == actor.id
    in_projects = Document.id.in_(project_document_ids)
    if scope is PaperSearchScope.LIBRARY:
        return in_library
    if scope is PaperSearchScope.PROJECTS:
        return in_projects
    return or_(in_library, in_projects)


def _matching_fields(document: Document, query: str, *, has_passage: bool) -> list[str]:
    needle = query.casefold()
    fields: list[str] = []
    candidates = (
        ("title", document.title),
        ("authors", " ".join(document.authors or [])),
        ("keywords", " ".join(document.keywords or [])),
        ("abstract", document.abstract),
    )
    for name, value in candidates:
        if value and needle in value.casefold():
            fields.append(name)
    if has_passage or (
        document.raw_content and needle in document.raw_content.casefold()
    ):
        fields.append("body")
    return fields


def _fallback_snippet(document: Document, query: str) -> PaperSearchSnippet | None:
    if not document.raw_content:
        return None
    lines = document.raw_content.splitlines()
    needle = query.casefold()
    for index, line in enumerate(lines):
        if needle in line.casefold():
            start = max(index - 1, 0)
            end = min(index + 2, len(lines))
            return PaperSearchSnippet(
                text="\n".join(lines[start:end])[:1_200],
                start_line=start + 1,
                end_line=end,
            )
    return None


def _matching_passages(
    db: Session,
    *,
    document_ids: list[UUID],
    text_query: object,
) -> dict[UUID, list[PaperSearchSnippet]]:
    if not document_ids:
        return {}
    passage_rank = func.ts_rank_cd(DocumentPassage.ts_vector, text_query)
    ranked = (
        select(
            DocumentPassage.document_id.label("document_id"),
            DocumentPassage.start_line.label("start_line"),
            DocumentPassage.end_line.label("end_line"),
            DocumentPassage.content.label("content"),
            func.row_number()
            .over(
                partition_by=DocumentPassage.document_id,
                order_by=(passage_rank.desc(), DocumentPassage.start_line),
            )
            .label("position"),
        )
        .where(
            DocumentPassage.document_id.in_(document_ids),
            DocumentPassage.ts_vector.op("@@")(text_query),
        )
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.document_id,
            ranked.c.start_line,
            ranked.c.end_line,
            ranked.c.content,
        )
        .where(ranked.c.position <= 3)
        .order_by(ranked.c.document_id, ranked.c.position)
    ).all()
    snippets: defaultdict[UUID, list[PaperSearchSnippet]] = defaultdict(list)
    for document_id, start_line, end_line, content in rows:
        snippets[document_id].append(
            PaperSearchSnippet(
                text=content[:1_200],
                start_line=start_line,
                end_line=end_line,
            )
        )
    return dict(snippets)


class PostgresPaperSearch:
    """Replaceable FTS implementation behind the PaperSearchPort."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def search(
        self,
        *,
        actor: Actor,
        request: PaperSearchQuery,
    ) -> PaperSearchResponse:
        text_query = func.websearch_to_tsquery("pg_catalog.english", request.query)
        visibility = _visibility_condition(
            actor=actor,
            scope=request.scope,
            project_document_ids=request.accessible_project_document_ids,
        )
        statement = (
            select(Document, LibraryPaper)
            .outerjoin(
                LibraryPaper,
                and_(
                    LibraryPaper.document_id == Document.id,
                    LibraryPaper.user_id == actor.id,
                ),
            )
            .where(
                visibility,
                Document.ts_vector.op("@@")(text_query),
            )
        )
        if request.filters.published_from is not None:
            statement = statement.where(
                Document.publish_date >= request.filters.published_from
            )
        if request.filters.published_to is not None:
            statement = statement.where(
                Document.publish_date <= request.filters.published_to
            )
        if request.filters.document_ids is not None:
            statement = statement.where(Document.id.in_(request.filters.document_ids))

        rank = func.ts_rank_cd(Document.ts_vector, text_query)
        if request.sort is PaperSearchSort.RECENT:
            statement = statement.order_by(
                Document.created_at.desc(),
                Document.id,
            )
        else:
            statement = statement.order_by(
                rank.desc(),
                LibraryPaper.last_accessed_at.desc().nullslast(),
                Document.id,
            )

        total = int(
            self._db.scalar(
                select(func.count()).select_from(statement.order_by(None).subquery())
            )
            or 0
        )
        rows = self._db.execute(
            statement.offset(request.offset).limit(request.limit)
        ).all()
        document_ids = [document.id for document, _entry in rows]
        passages = _matching_passages(
            self._db,
            document_ids=document_ids,
            text_query=text_query,
        )

        items: list[PaperSearchResult] = []
        for document, library_entry in rows:
            snippets = passages.get(document.id, [])
            if not snippets:
                fallback = _fallback_snippet(document, request.query)
                if fallback is not None:
                    snippets = [fallback]
            items.append(
                PaperSearchResult(
                    document_id=document.id,
                    title=document.title,
                    authors=document.authors,
                    abstract=document.abstract,
                    status=(
                        library_entry.status
                        if library_entry is not None
                        else document.processing_status
                    ),
                    publish_date=document.publish_date,
                    created_at=document.created_at,
                    last_accessed_at=(
                        library_entry.last_accessed_at
                        if library_entry is not None
                        else document.created_at
                    ),
                    preview_url=(
                        s3_service.generate_presigned_url(document.preview_s3_key)
                        if document.preview_s3_key
                        else None
                    ),
                    matched_fields=_matching_fields(
                        document,
                        request.query,
                        has_passage=bool(snippets),
                    ),
                    snippets=snippets,
                )
            )
        return PaperSearchResponse(items=items, total=total)

    def stats(
        self,
        *,
        actor: Actor,
        accessible_project_document_ids: tuple[UUID, ...],
    ) -> PaperSearchStats:
        total = int(
            self._db.scalar(
                select(func.count(Document.id.distinct()))
                .outerjoin(
                    LibraryPaper,
                    and_(
                        LibraryPaper.document_id == Document.id,
                        LibraryPaper.user_id == actor.id,
                    ),
                )
                .where(
                    or_(
                        LibraryPaper.user_id == actor.id,
                        Document.id.in_(accessible_project_document_ids),
                    )
                )
            )
            or 0
        )
        return PaperSearchStats(total_papers=total, searchable_items=total)
