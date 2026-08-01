"""Create deterministic AI highlight threads from parsed Document content."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from app.database.models import RoleType
from app.helpers.parser import get_start_page_from_offset
from app.llm.utils import find_offsets
from app.modules.papers.infrastructure.repository import document_repository
from app.bootstrap.adapters.research_repository import (
    HighlightThreadCreate,
    research_repository,
)
from app.modules.papers.application.contracts.extraction import PaperMetadataExtraction
from app.shared.application import Actor
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedDocumentContent:
    raw_content: str
    page_offsets: dict[int, tuple[int, int]]


@dataclass(frozen=True, slots=True)
class CreatedAiHighlights:
    thread_ids: tuple[uuid.UUID, ...]
    comment_ids: tuple[uuid.UUID, ...]


def require_parsed_content(
    db: Session,
    *,
    document_id: uuid.UUID,
    user: Actor,
) -> ParsedDocumentContent:
    document = document_repository.find_accessible(
        db,
        document_id=document_id,
        user=user,
    )
    if document is None:
        raise ValueError("document_not_found")
    if not document.raw_content:
        raise ValueError("document_content_unavailable")
    offsets = (
        {
            page: (bounds[0], bounds[1])
            for page, bounds in document.page_offset_map.items()
            if len(bounds) >= 2
        }
        if document.page_offset_map
        else {}
    )
    return ParsedDocumentContent(
        raw_content=document.raw_content,
        page_offsets=offsets,
    )


def create_ai_highlights(
    db: Session,
    *,
    document_id: uuid.UUID,
    metadata: PaperMetadataExtraction,
    user: Actor,
) -> CreatedAiHighlights:
    if research_repository.has_assistant_highlight(
        db,
        document_id=document_id,
    ):
        logger.info(
            "research.ai_highlights.duplicate_skipped",
            extra={"document_id": str(document_id)},
        )
        return CreatedAiHighlights((), ())
    content = require_parsed_content(db, document_id=document_id, user=user)
    thread_ids: list[uuid.UUID] = []
    comment_ids: list[uuid.UUID] = []
    for highlight in metadata.highlights:
        offsets = find_offsets(highlight.text, content.raw_content)
        page_number = (
            get_start_page_from_offset(content.page_offsets, offsets[0])
            if offsets and content.page_offsets
            else None
        )
        item = research_repository.create_highlight_thread(
            db,
            document_id=document_id,
            user_id=user.id,
            create=HighlightThreadCreate(
                quote_text=highlight.text,
                start_offset=offsets[0],
                end_offset=offsets[1],
                page_number=page_number,
                position=None,
                color="blue",
                is_shared=True,
                content_role=RoleType.ASSISTANT,
            ),
            refresh_result=False,
        )
        comment = research_repository.add_comment(
            db,
            thread_id=item.id,
            user_id=user.id,
            content=highlight.annotation,
            content_role=RoleType.ASSISTANT,
            refresh_result=False,
        )
        thread_ids.append(item.id)
        comment_ids.append(comment.id)
    db.flush()
    return CreatedAiHighlights(
        thread_ids=tuple(thread_ids),
        comment_ids=tuple(comment_ids),
    )


__all__ = [
    "CreatedAiHighlights",
    "ParsedDocumentContent",
    "create_ai_highlights",
    "require_parsed_content",
]
