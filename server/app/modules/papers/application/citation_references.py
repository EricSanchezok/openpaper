"""Map paper-summary citations to the shared typed message reference contract."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.conversations.application.contracts.answer_packet import (
    DocumentAnswerSource,
    MessageReferences,
)
from app.modules.papers.application.contracts.extraction import ResponseCitation


def map_summary_references(
    citations: Sequence[ResponseCitation],
    *,
    document_id: UUID,
    title: str | None,
) -> MessageReferences:
    return MessageReferences(
        citations=[
            DocumentAnswerSource(
                key=citation.index,
                document_id=document_id,
                title=title,
                reference=citation.text,
            )
            for citation in citations
        ]
    )
