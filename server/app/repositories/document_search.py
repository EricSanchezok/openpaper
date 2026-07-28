"""Passage indexing and full-text search for accessible Documents."""

from __future__ import annotations

import logging
import re
import uuid
from typing import TypedDict

from app.database.crud.sanitization import sanitize_for_postgres
from app.database.models import PaperTag
from sqlalchemy import select, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class PassageInsert(TypedDict):
    start_line: int
    end_line: int
    content: str


class DocumentSearchRepository:
    @staticmethod
    def build_passages(
        raw_content: str,
        *,
        window: int = 5,
        stride: int = 3,
    ) -> list[PassageInsert]:
        lines = raw_content.split("\n")
        return [
            {
                "start_line": index + 1,
                "end_line": index + len(lines[index : index + window]),
                "content": "\n".join(lines[index : index + window]),
            }
            for index in range(0, len(lines), stride)
        ]

    def replace_passage_index(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        raw_content: str,
        window: int = 5,
        stride: int = 3,
    ) -> None:
        sanitized = sanitize_for_postgres(raw_content)
        if sanitized != raw_content:
            logger.warning(
                "Sanitized null characters before indexing document passages",
                extra={"document_id": str(document_id)},
            )
        db.execute(
            text("DELETE FROM scholens.paper_passages WHERE paper_id = :paper_id"),
            {"paper_id": document_id},
        )
        passages = self.build_passages(
            sanitized,
            window=window,
            stride=stride,
        )
        if passages:
            db.execute(
                text(
                    """
                    INSERT INTO scholens.paper_passages
                        (paper_id, start_line, end_line, content)
                    VALUES (:paper_id, :start_line, :end_line, :content)
                    """
                ),
                [{"paper_id": document_id, **passage} for passage in passages],
            )
        db.flush()

    def matching_lines(
        self,
        db: Session,
        *,
        user_id: int,
        query: str,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[str, int, str]]:
        raw_terms = [
            term.strip() for term in query.replace("-", " ").split("|") if term.strip()
        ]
        if not raw_terms:
            return []
        search_terms = sorted({term.lower() for term in raw_terms})
        regex_query = "|".join(re.escape(term) for term in search_terms)
        fts_query = " || ".join(
            f"phraseto_tsquery('english', :term_{index})"
            for index in range(len(search_terms))
        )
        sql = f"""
            SELECT pp.paper_id::text, pp.start_line, pp.content
            FROM scholens.paper_passages pp
            JOIN scholens.documents d ON d.id = pp.paper_id
            JOIN scholens.library_papers lp ON lp.document_id = d.id
            WHERE pp.ts_vector @@ ({fts_query})
              AND lp.user_id = :user_id
        """
        params: dict[str, object] = {"user_id": user_id}
        for index, term in enumerate(search_terms):
            params[f"term_{index}"] = term
        if document_ids:
            sql += " AND pp.paper_id = ANY(:paper_ids)"
            params["paper_ids"] = document_ids
        sql += " ORDER BY pp.paper_id, pp.start_line"

        rows = db.execute(text(sql), params).fetchall()
        matches: dict[tuple[str, int], tuple[str, int, str]] = {}
        for document_id, start_line, content in rows:
            for offset, line in enumerate(content.split("\n")):
                if re.search(regex_query, line, re.IGNORECASE):
                    key = (document_id, start_line + offset)
                    matches.setdefault(key, (document_id, start_line + offset, line))
        return sorted(matches.values(), key=lambda result: (result[0], result[1]))

    def list_topics(self, db: Session, *, user_id: int) -> list[str]:
        names = db.scalars(
            select(PaperTag.name)
            .join(PaperTag.library_papers)
            .where(PaperTag.user_id == user_id)
            .distinct()
        ).all()
        return [name.strip() for name in names if name and name.strip()]


document_search_repository = DocumentSearchRepository()
