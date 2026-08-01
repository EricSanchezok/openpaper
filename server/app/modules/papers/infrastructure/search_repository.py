"""Passage indexing and topic queries for canonical Documents."""

from __future__ import annotations

import logging
import uuid
from typing import TypedDict

from app.helpers.postgres import sanitize_for_postgres
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
                "paper_search.passages.null_characters_sanitized",
                extra={"document_id": str(document_id)},
            )
        db.execute(
            text(
                "DELETE FROM scholens.document_passages WHERE document_id = :document_id"
            ),
            {"document_id": document_id},
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
                    INSERT INTO scholens.document_passages
                        (document_id, start_line, end_line, content)
                    VALUES (:document_id, :start_line, :end_line, :content)
                    """
                ),
                [{"document_id": document_id, **passage} for passage in passages],
            )
        db.flush()

    def list_topics(self, db: Session, *, user_id: int) -> list[str]:
        names = db.scalars(
            select(PaperTag.name)
            .join(PaperTag.library_papers)
            .where(PaperTag.user_id == user_id)
            .distinct()
        ).all()
        return [name.strip() for name in names if name and name.strip()]


document_search_repository = DocumentSearchRepository()
