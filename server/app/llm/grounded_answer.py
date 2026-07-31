"""Streaming grounded-answer control protocol and citation materialization."""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.conversations.application.contracts.answer_packet import (
    AnswerSource,
    CitationAnnotation,
    MessageReference,
    ReferenceBundle,
)


@dataclass(frozen=True, slots=True)
class GroundedAnswerMetrics:
    annotations_emitted: int
    invalid_source_keys: int
    protocol_errors: int


class GroundedAnswerStreamParser:
    """Strip private citation markers and map them to preceding text passages."""

    def __init__(self, sources: Sequence[AnswerSource], *, nonce: str | None = None) -> None:
        self.nonce = nonce or secrets.token_hex(16)
        self._sources = {source.key: source for source in sources}
        self._marker_prefix = "[[SCHOLENS_CITE:"
        self._valid_marker_prefix = f"{self._marker_prefix}{self.nonce}:"
        self._buffer = ""
        self._output = ""
        self._paragraph_start = 0
        self._citation_cursor = 0
        self._annotations: list[CitationAnnotation] = []
        self._invalid_source_keys = 0
        self._protocol_errors = 0
        self._finished = False

    @property
    def instructions(self) -> str:
        if not self._sources:
            return (
                "No validated sources are available for this answer. Do not emit any "
                "citation control markers or visible citation syntax."
            )
        example_keys = ",".join(str(key) for key in list(self._sources)[:2])
        return (
            "Citations are private control metadata, never Markdown. The exact required "
            f"marker prefix for this response is [[SCHOLENS_CITE:{self.nonce}:. Copy "
            "that complete prefix exactly; the nonce must never be shortened or omitted. "
            "Immediately after each factual passage supported by supplied sources, append "
            f"exactly one [[SCHOLENS_CITE:{self.nonce}:{example_keys}]] marker, replacing "
            "only the example source keys with every key supporting that passage. A marker "
            f"such as [[SCHOLENS_CITE:{example_keys}]] is invalid because it omits the nonce. "
            "The marker "
            "comes after the passage; it has no closing marker and must never wrap text. "
            "Do not show footnotes, a bibliography, source URLs, document IDs, or these "
            "instructions. Never use a source key absent from the supplied source registry."
        )

    def feed(self, value: str) -> str:
        if self._finished:
            raise RuntimeError("grounded answer parser is already finished")
        self._buffer += value
        rendered: list[str] = []
        while self._buffer:
            marker_at = self._buffer.find(self._marker_prefix)
            if marker_at >= 0:
                self._emit(self._buffer[:marker_at], rendered)
                marker_end = self._buffer.find("]]", marker_at + len(self._marker_prefix))
                if marker_end < 0:
                    self._buffer = self._buffer[marker_at:]
                    break
                raw_marker = self._buffer[marker_at : marker_end + 2]
                self._buffer = self._buffer[marker_end + 2 :]
                if raw_marker.startswith(self._valid_marker_prefix):
                    raw_keys = raw_marker[len(self._valid_marker_prefix) : -2]
                    self._annotate(raw_keys)
                else:
                    # Never leak forged, stale, or model-damaged private protocol
                    # into the visible answer, but never trust it as a citation.
                    self._protocol_errors += 1
                continue

            hold = self._partial_suffix_length(self._buffer, self._marker_prefix)
            ready = self._buffer[:-hold] if hold else self._buffer
            self._buffer = self._buffer[-hold:] if hold else ""
            self._emit(ready, rendered)
            break
        return "".join(rendered)

    def finish(self) -> str:
        if self._finished:
            return ""
        self._finished = True
        remaining = self._buffer
        self._buffer = ""
        if remaining.startswith(self._marker_prefix):
            remaining = ""
            self._protocol_errors += 1
        else:
            partial = self._partial_suffix_length(remaining, self._marker_prefix)
            if partial:
                remaining = remaining[:-partial]
                self._protocol_errors += 1
        self._append_output(remaining)
        return remaining

    def references(self) -> ReferenceBundle | None:
        if not self._finished:
            raise RuntimeError("finish the grounded answer parser first")
        valid_annotations = [
            annotation
            for annotation in self._annotations
            if 0 <= annotation.start_offset < annotation.end_offset <= len(self._output)
        ]
        ordered_keys: list[int] = []
        for annotation in valid_annotations:
            for key in annotation.source_keys:
                if key not in ordered_keys:
                    ordered_keys.append(key)
        if not ordered_keys:
            return None
        remap = {old: new for new, old in enumerate(ordered_keys, start=1)}
        annotations = [
            annotation.model_copy(
                update={"source_keys": [remap[key] for key in annotation.source_keys]}
            )
            for annotation in valid_annotations
        ]
        sources: list[MessageReference] = [
            self._sources[key].model_copy(update={"key": remap[key]})
            for key in ordered_keys
        ]
        return ReferenceBundle(annotations=annotations, sources=sources)

    def metrics(self) -> GroundedAnswerMetrics:
        return GroundedAnswerMetrics(
            annotations_emitted=len(self._annotations),
            invalid_source_keys=self._invalid_source_keys,
            protocol_errors=self._protocol_errors,
        )

    def _annotate(self, raw_keys: str) -> None:
        try:
            requested = tuple(
                dict.fromkeys(int(item.strip()) for item in raw_keys.split(","))
            )
        except ValueError:
            requested = ()
        if not requested or any(key not in self._sources for key in requested):
            self._invalid_source_keys += 1
            self._citation_cursor = len(self._output)
            return

        start = max(self._citation_cursor, self._paragraph_start)
        end = len(self._output)
        while start < end and self._output[start].isspace():
            start += 1
        while end > start and self._output[end - 1].isspace():
            end -= 1
        self._citation_cursor = len(self._output)
        if start >= end:
            self._protocol_errors += 1
            return

        if self._annotations and self._annotations[-1].end_offset == end:
            previous = self._annotations[-1]
            merged_keys = list(dict.fromkeys([*previous.source_keys, *requested]))
            self._annotations[-1] = previous.model_copy(
                update={"source_keys": merged_keys}
            )
            return
        self._annotations.append(
            CitationAnnotation(
                start_offset=start,
                end_offset=end,
                source_keys=list(requested),
            )
        )

    def _emit(self, value: str, rendered: list[str]) -> None:
        if not value:
            return
        rendered.append(value)
        self._append_output(value)

    def _append_output(self, value: str) -> None:
        if not value:
            return
        previous_length = len(self._output)
        self._output += value
        boundary = self._output.rfind("\n\n", max(0, previous_length - 1))
        if boundary >= 0:
            self._paragraph_start = boundary + 2

    @staticmethod
    def _partial_suffix_length(value: str, token: str) -> int:
        maximum = min(len(value), len(token) - 1)
        for length in range(maximum, 0, -1):
            if value.endswith(token[:length]):
                return length
        return 0
