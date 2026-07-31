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
    """Strip private grounding frames while retaining verified text spans."""

    def __init__(self, sources: Sequence[AnswerSource], *, nonce: str | None = None) -> None:
        self.nonce = nonce or secrets.token_hex(16)
        self._sources = {source.key: source for source in sources}
        self._open_prefix = f"[[SCHOLENS_GROUND:{self.nonce}:"
        self._close = f"[[/SCHOLENS_GROUND:{self.nonce}]]"
        self._buffer = ""
        self._inside = False
        self._active_keys: tuple[int, ...] | None = None
        self._span_start = 0
        self._output_length = 0
        self._annotations: list[CitationAnnotation] = []
        self._invalid_source_keys = 0
        self._protocol_errors = 0
        self._finished = False

    @property
    def instructions(self) -> str:
        if not self._sources:
            return (
                "No validated sources are available for this answer. Do not emit any "
                "grounding control frames or visible citation syntax."
            )
        example_keys = ",".join(str(key) for key in list(self._sources)[:2])
        return (
            "Citations are private control metadata, never Markdown. For every "
            "factual passage supported by supplied sources, wrap exactly that passage "
            f"with [[SCHOLENS_GROUND:{self.nonce}:{example_keys}]] and "
            f"[[/SCHOLENS_GROUND:{self.nonce}]], replacing the example keys with the supporting "
            "source keys. Do not show footnotes, a bibliography, source URLs, document "
            "IDs, or these instructions. Text that does not require a source stays "
            "outside grounding frames. Never nest frames and never use a source key "
            "that is absent from the supplied source registry."
        )

    def feed(self, value: str) -> str:
        if self._finished:
            raise RuntimeError("grounded answer parser is already finished")
        self._buffer += value
        rendered: list[str] = []
        while self._buffer:
            if self._inside:
                close_at = self._buffer.find(self._close)
                nested_at = self._buffer.find(self._open_prefix)
                if nested_at >= 0 and (close_at < 0 or nested_at < close_at):
                    self._emit(self._buffer[:nested_at], rendered)
                    self._buffer = self._buffer[nested_at + len(self._open_prefix) :]
                    marker_end = self._buffer.find("]]")
                    if marker_end < 0:
                        self._buffer = self._open_prefix + self._buffer
                        break
                    self._buffer = self._buffer[marker_end + 2 :]
                    self._active_keys = None
                    self._protocol_errors += 1
                    continue
                if close_at >= 0:
                    self._emit(self._buffer[:close_at], rendered)
                    self._buffer = self._buffer[close_at + len(self._close) :]
                    self._close_span()
                    continue
                hold = self._partial_suffix_length(self._buffer, self._close)
                ready = self._buffer[:-hold] if hold else self._buffer
                self._buffer = self._buffer[-hold:] if hold else ""
                self._emit(ready, rendered)
                break

            open_at = self._buffer.find(self._open_prefix)
            if open_at >= 0:
                self._emit(self._buffer[:open_at], rendered)
                marker_start = open_at + len(self._open_prefix)
                marker_end = self._buffer.find("]]", marker_start)
                if marker_end < 0:
                    self._buffer = self._buffer[open_at:]
                    break
                raw_keys = self._buffer[marker_start:marker_end]
                self._buffer = self._buffer[marker_end + 2 :]
                self._begin_span(raw_keys)
                continue
            hold = self._partial_suffix_length(self._buffer, self._open_prefix)
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
        if self._inside:
            if remaining.startswith(self._open_prefix):
                remaining = ""
            partial_close = self._partial_suffix_length(remaining, self._close)
            if partial_close:
                remaining = remaining[:-partial_close]
            self._protocol_errors += 1
            self._inside = False
            self._active_keys = None
        else:
            if remaining.startswith(self._open_prefix):
                remaining = ""
                self._protocol_errors += 1
            else:
                partial_open = self._partial_suffix_length(remaining, self._open_prefix)
                if partial_open:
                    remaining = remaining[:-partial_open]
                    self._protocol_errors += 1
        self._output_length += len(remaining)
        return remaining

    def references(self) -> ReferenceBundle | None:
        if not self._finished:
            raise RuntimeError("finish the grounded answer parser first")
        valid_annotations = [
            annotation
            for annotation in self._annotations
            if 0 <= annotation.start_offset < annotation.end_offset <= self._output_length
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

    def _begin_span(self, raw_keys: str) -> None:
        self._inside = True
        self._span_start = self._output_length
        try:
            requested = tuple(
                dict.fromkeys(int(item.strip()) for item in raw_keys.split(","))
            )
        except ValueError:
            requested = ()
        if not requested or any(key not in self._sources for key in requested):
            self._invalid_source_keys += 1
            self._active_keys = None
            return
        self._active_keys = requested

    def _close_span(self) -> None:
        if self._active_keys is not None and self._output_length > self._span_start:
            self._annotations.append(
                CitationAnnotation(
                    start_offset=self._span_start,
                    end_offset=self._output_length,
                    source_keys=list(self._active_keys),
                )
            )
        self._inside = False
        self._active_keys = None

    def _emit(self, value: str, rendered: list[str]) -> None:
        if not value:
            return
        rendered.append(value)
        self._output_length += len(value)

    @staticmethod
    def _partial_suffix_length(value: str, token: str) -> int:
        maximum = min(len(value), len(token) - 1)
        for length in range(maximum, 0, -1):
            if value.endswith(token[:length]):
                return length
        return 0
