"""Materialize paper-summary markers at the Papers/Conversation boundary."""

import re
from collections.abc import Sequence
from uuid import UUID

from app.modules.conversations.application.contracts.answer_packet import (
    CitationAnnotation,
    DocumentAnswerSource,
    ReferenceBundle,
)
from app.modules.papers.application.contracts.extraction import ResponseCitation


_SUMMARY_MARKER = re.compile(r"\[\^(\d+(?:\s*,\s*\^?\d+)*)\]")
_CLAIM_BOUNDARIES = ".!?。！？\n"


def materialize_summary_references(
    summary: str,
    citations: Sequence[ResponseCitation],
    *,
    document_id: UUID,
    title: str | None,
) -> tuple[str, ReferenceBundle | None]:
    by_index = {citation.index: citation for citation in citations}
    clean_parts: list[str] = []
    annotations_with_old_keys: list[tuple[int, int, list[int]]] = []
    cursor = 0
    output_length = 0
    for match in _SUMMARY_MARKER.finditer(summary):
        prefix = summary[cursor : match.start()]
        clean_parts.append(prefix)
        output_length += len(prefix)
        requested = [
            int(value.strip().removeprefix("^")) for value in match.group(1).split(",")
        ]
        valid = list(dict.fromkeys(key for key in requested if key in by_index))
        if valid and output_length:
            current = "".join(clean_parts)
            boundary = max(
                current.rfind(char, 0, output_length - 1) for char in _CLAIM_BOUNDARIES
            )
            start = boundary + 1
            while start < output_length and current[start].isspace():
                start += 1
            if start < output_length:
                annotations_with_old_keys.append((start, output_length, valid))
        cursor = match.end()
    suffix = summary[cursor:]
    clean_parts.append(suffix)
    clean_summary = "".join(clean_parts)

    ordered_old_keys: list[int] = []
    for _, _, keys in annotations_with_old_keys:
        for key in keys:
            if key not in ordered_old_keys:
                ordered_old_keys.append(key)
    if not ordered_old_keys:
        return clean_summary, None
    remap = {old: new for new, old in enumerate(ordered_old_keys, start=1)}
    bundle = ReferenceBundle(
        annotations=[
            CitationAnnotation(
                start_offset=start,
                end_offset=end,
                source_keys=[remap[key] for key in keys],
            )
            for start, end, keys in annotations_with_old_keys
        ],
        sources=[
            DocumentAnswerSource(
                key=remap[key],
                document_id=document_id,
                title=title,
                reference=by_index[key].text,
            )
            for key in ordered_old_keys
        ],
    )
    return clean_summary, bundle
